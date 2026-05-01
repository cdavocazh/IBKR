"""
Backtesting Engine for ES Futures

Features:
- Event-driven backtesting
- Realistic order execution with slippage
- Commission modeling
- Position and P&L tracking
- Multiple timeframe support
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Callable
import pandas as pd
import numpy as np


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class OrderStatus(Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass
class Order:
    """Represents a trading order."""
    id: int
    timestamp: datetime
    side: OrderSide
    quantity: int
    order_type: OrderType = OrderType.MARKET
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    fill_price: Optional[float] = None
    fill_timestamp: Optional[datetime] = None
    commission: float = 0.0


@dataclass
class Position:
    """Represents current position."""
    quantity: int = 0
    avg_price: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0

    @property
    def is_long(self) -> bool:
        return self.quantity > 0

    @property
    def is_short(self) -> bool:
        return self.quantity < 0

    @property
    def is_flat(self) -> bool:
        return self.quantity == 0


@dataclass
class Trade:
    """Represents a completed trade."""
    entry_time: datetime
    exit_time: datetime
    side: str
    quantity: int
    entry_price: float
    exit_price: float
    pnl: float
    commission: float
    bars_held: int


@dataclass
class Bar:
    """Represents a single OHLCV bar."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class BacktestEngine:
    """
    Event-driven backtesting engine for ES futures.

    ES Contract Specifications:
    - Tick size: 0.25 points
    - Point value: $50 per point ($12.50 per tick)
    - Margin: ~$13,000 per contract (varies)
    """

    # ES specifications
    TICK_SIZE = 0.25
    POINT_VALUE = 50.0  # $50 per point
    TICK_VALUE = POINT_VALUE * TICK_SIZE  # $12.50 per tick

    def __init__(
        self,
        data: pd.DataFrame,
        initial_capital: float = 100000.0,
        commission_per_contract: float = 2.25,
        slippage_ticks: int = 1,
        max_position: int = 10,
    ):
        """
        Initialize backtest engine.

        Args:
            data: DataFrame with OHLCV data (datetime index)
            initial_capital: Starting capital in USD
            commission_per_contract: Commission per contract per side
            slippage_ticks: Assumed slippage in ticks
            max_position: Maximum position size in contracts
        """
        self.data = data.copy()
        self.initial_capital = initial_capital
        self.commission_per_contract = commission_per_contract
        self.slippage_ticks = slippage_ticks
        self.slippage_points = slippage_ticks * self.TICK_SIZE
        self.max_position = max_position

        # State
        self.position = Position()
        self.capital = initial_capital
        self.orders: list[Order] = []
        self.trades: list[Trade] = []
        self.order_id_counter = 0

        # Current bar info
        self.current_bar: Optional[Bar] = None
        self.current_index: int = 0
        self.bar_count: int = len(data)

        # Equity tracking
        self.equity_curve: list[tuple[datetime, float]] = []

        # Strategy callback
        self.strategy_callback: Optional[Callable] = None

        # Entry tracking for trade records
        self._entry_bar_index: Optional[int] = None
        self._entry_time: Optional[datetime] = None
        self._entry_price: Optional[float] = None
        self._entry_side: Optional[str] = None

    def set_strategy(self, callback: Callable):
        """
        Set strategy callback function.

        The callback receives (engine, bar) and should return orders.
        """
        self.strategy_callback = callback

    def run(self, strategy=None) -> dict:
        """
        Run the backtest.

        Args:
            strategy: Optional Strategy instance with on_bar method

        Returns:
            Dictionary with results
        """
        if strategy:
            self.strategy_callback = strategy.on_bar

        if not self.strategy_callback:
            raise ValueError("No strategy set. Use set_strategy() or pass strategy to run()")

        print(f"Starting backtest with {self.bar_count} bars...")
        print(f"Initial capital: ${self.initial_capital:,.2f}")

        for idx, (timestamp, row) in enumerate(self.data.iterrows()):
            self.step_one_bar(idx, timestamp, row)

        # Close any open position at end
        if not self.position.is_flat:
            self._close_position("END_OF_BACKTEST")

        return self._generate_results()

    def step_one_bar(self, idx: int, timestamp, row) -> float:
        """Process one bar of data — extracted from run() so a step-callable
        BacktestRunner / Gym env can drive the loop bar-by-bar.

        Returns the bar's equity value (capital + unrealized PnL).
        Strategy callback IS invoked here exactly as in run().
        """
        self.current_index = idx
        self.current_bar = Bar(
            timestamp=timestamp,
            open=row["open"],
            high=row["high"],
            low=row["low"],
            close=row["close"],
            volume=int(row.get("volume", 0)),
        )

        # Process pending orders
        self._process_orders()

        # Update unrealized P&L
        self._update_unrealized_pnl()

        # Call strategy
        if self.strategy_callback:
            self.strategy_callback(self, self.current_bar)

        # Record equity
        equity = self.capital + self.position.unrealized_pnl
        self.equity_curve.append((timestamp, equity))
        return float(equity)

    def finalize(self) -> dict:
        """Close any open position and return the results dict.
        Use after driving the loop yourself via step_one_bar()."""
        if not self.position.is_flat:
            self._close_position("END_OF_BACKTEST")
        return self._generate_results()

    def buy(
        self,
        quantity: int = 1,
        order_type: OrderType = OrderType.MARKET,
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
    ) -> Order:
        """Place a buy order."""
        return self._place_order(
            OrderSide.BUY, quantity, order_type, limit_price, stop_price
        )

    def sell(
        self,
        quantity: int = 1,
        order_type: OrderType = OrderType.MARKET,
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
    ) -> Order:
        """Place a sell order."""
        return self._place_order(
            OrderSide.SELL, quantity, order_type, limit_price, stop_price
        )

    def close_position(self) -> Optional[Order]:
        """Close current position with market order."""
        if self.position.is_flat:
            return None

        if self.position.is_long:
            return self.sell(quantity=self.position.quantity)
        else:
            return self.buy(quantity=abs(self.position.quantity))

    def cancel_order(self, order_id: int) -> bool:
        """Cancel a pending order."""
        for order in self.orders:
            if order.id == order_id and order.status == OrderStatus.PENDING:
                order.status = OrderStatus.CANCELLED
                return True
        return False

    def cancel_all_orders(self):
        """Cancel all pending orders."""
        for order in self.orders:
            if order.status == OrderStatus.PENDING:
                order.status = OrderStatus.CANCELLED

    def _place_order(
        self,
        side: OrderSide,
        quantity: int,
        order_type: OrderType,
        limit_price: Optional[float],
        stop_price: Optional[float],
    ) -> Order:
        """Internal order placement."""
        self.order_id_counter += 1

        order = Order(
            id=self.order_id_counter,
            timestamp=self.current_bar.timestamp,
            side=side,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            stop_price=stop_price,
        )

        # Validate position limits
        projected_position = self.position.quantity
        if side == OrderSide.BUY:
            projected_position += quantity
        else:
            projected_position -= quantity

        if abs(projected_position) > self.max_position:
            order.status = OrderStatus.REJECTED
            return order

        self.orders.append(order)
        return order

    def _process_orders(self):
        """Process pending orders against current bar."""
        for order in self.orders:
            if order.status != OrderStatus.PENDING:
                continue

            fill_price = self._get_fill_price(order)
            if fill_price is not None:
                self._execute_order(order, fill_price)

    def _get_fill_price(self, order: Order) -> Optional[float]:
        """Determine fill price for order, or None if not filled."""
        bar = self.current_bar

        if order.order_type == OrderType.MARKET:
            # Market orders fill at open with slippage
            if order.side == OrderSide.BUY:
                return bar.open + self.slippage_points
            else:
                return bar.open - self.slippage_points

        elif order.order_type == OrderType.LIMIT:
            if order.side == OrderSide.BUY:
                if bar.low <= order.limit_price:
                    return min(order.limit_price, bar.open)
            else:
                if bar.high >= order.limit_price:
                    return max(order.limit_price, bar.open)

        elif order.order_type == OrderType.STOP:
            if order.side == OrderSide.BUY:
                if bar.high >= order.stop_price:
                    return order.stop_price + self.slippage_points
            else:
                if bar.low <= order.stop_price:
                    return order.stop_price - self.slippage_points

        return None

    def _execute_order(self, order: Order, fill_price: float):
        """Execute an order at given price."""
        order.status = OrderStatus.FILLED
        order.fill_price = fill_price
        order.fill_timestamp = self.current_bar.timestamp
        order.commission = self.commission_per_contract * order.quantity

        # Calculate position change
        quantity_change = order.quantity if order.side == OrderSide.BUY else -order.quantity

        # Track for trade records
        was_flat = self.position.is_flat
        old_quantity = self.position.quantity

        # Update position
        if self.position.is_flat:
            # Opening new position
            self.position.quantity = quantity_change
            self.position.avg_price = fill_price
            self._entry_bar_index = self.current_index
            self._entry_time = self.current_bar.timestamp
            self._entry_price = fill_price
            self._entry_side = "LONG" if quantity_change > 0 else "SHORT"

        elif (self.position.is_long and order.side == OrderSide.BUY) or \
             (self.position.is_short and order.side == OrderSide.SELL):
            # Adding to position
            total_cost = (self.position.avg_price * abs(self.position.quantity) +
                         fill_price * order.quantity)
            self.position.quantity += quantity_change
            self.position.avg_price = total_cost / abs(self.position.quantity)

        else:
            # Reducing or reversing position
            close_quantity = min(abs(old_quantity), order.quantity)

            # Calculate realized P&L
            if self.position.is_long:
                pnl = (fill_price - self.position.avg_price) * close_quantity * self.POINT_VALUE
            else:
                pnl = (self.position.avg_price - fill_price) * close_quantity * self.POINT_VALUE

            self.position.realized_pnl += pnl

            # Record trade
            if self._entry_time:
                trade = Trade(
                    entry_time=self._entry_time,
                    exit_time=self.current_bar.timestamp,
                    side=self._entry_side,
                    quantity=close_quantity,
                    entry_price=self._entry_price,
                    exit_price=fill_price,
                    pnl=pnl - order.commission,
                    commission=order.commission,
                    bars_held=self.current_index - self._entry_bar_index,
                )
                self.trades.append(trade)

            # Update position
            self.position.quantity += quantity_change

            if self.position.is_flat:
                self.position.avg_price = 0.0
                self._entry_bar_index = None
                self._entry_time = None
                self._entry_price = None
                self._entry_side = None
            elif abs(quantity_change) > abs(old_quantity):
                # Position reversed
                remaining = abs(quantity_change) - abs(old_quantity)
                self.position.avg_price = fill_price
                self._entry_bar_index = self.current_index
                self._entry_time = self.current_bar.timestamp
                self._entry_price = fill_price
                self._entry_side = "LONG" if self.position.is_long else "SHORT"

        # Deduct commission from capital
        self.capital -= order.commission

    def _update_unrealized_pnl(self):
        """Update unrealized P&L based on current price."""
        if self.position.is_flat:
            self.position.unrealized_pnl = 0.0
        else:
            current_price = self.current_bar.close
            if self.position.is_long:
                self.position.unrealized_pnl = (
                    (current_price - self.position.avg_price) *
                    self.position.quantity * self.POINT_VALUE
                )
            else:
                self.position.unrealized_pnl = (
                    (self.position.avg_price - current_price) *
                    abs(self.position.quantity) * self.POINT_VALUE
                )

    def _close_position(self, reason: str):
        """Force close position at end of backtest."""
        if self.position.is_flat:
            return

        if self.position.is_long:
            self.sell(quantity=self.position.quantity)
        else:
            self.buy(quantity=abs(self.position.quantity))

        self._process_orders()

    def _generate_results(self) -> dict:
        """Generate backtest results summary."""
        equity_df = pd.DataFrame(
            self.equity_curve, columns=["timestamp", "equity"]
        ).set_index("timestamp")

        final_equity = equity_df["equity"].iloc[-1]
        total_return = (final_equity / self.initial_capital - 1) * 100
        total_pnl = final_equity - self.initial_capital

        # Trade statistics
        if self.trades:
            trades_df = pd.DataFrame([{
                "entry_time": t.entry_time,
                "exit_time": t.exit_time,
                "side": t.side,
                "quantity": t.quantity,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl": t.pnl,
                "commission": t.commission,
                "bars_held": t.bars_held,
            } for t in self.trades])

            winning_trades = trades_df[trades_df["pnl"] > 0]
            losing_trades = trades_df[trades_df["pnl"] <= 0]

            win_rate = len(winning_trades) / len(trades_df) * 100 if len(trades_df) > 0 else 0
            avg_win = winning_trades["pnl"].mean() if len(winning_trades) > 0 else 0
            avg_loss = losing_trades["pnl"].mean() if len(losing_trades) > 0 else 0
            profit_factor = (
                abs(winning_trades["pnl"].sum() / losing_trades["pnl"].sum())
                if len(losing_trades) > 0 and losing_trades["pnl"].sum() != 0
                else float("inf")
            )
        else:
            trades_df = pd.DataFrame()
            win_rate = 0
            avg_win = 0
            avg_loss = 0
            profit_factor = 0

        results = {
            "initial_capital": self.initial_capital,
            "final_equity": final_equity,
            "total_pnl": total_pnl,
            "total_return_pct": total_return,
            "total_trades": len(self.trades),
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "max_drawdown": self._calculate_max_drawdown(equity_df),
            "sharpe_ratio": self._calculate_sharpe(equity_df),
            "equity_curve": equity_df,
            "trades": trades_df,
        }

        return results

    def _calculate_max_drawdown(self, equity_df: pd.DataFrame) -> float:
        """Calculate maximum drawdown percentage."""
        equity = equity_df["equity"]
        peak = equity.expanding().max()
        drawdown = (equity - peak) / peak * 100
        return abs(drawdown.min())

    def _calculate_sharpe(
        self,
        equity_df: pd.DataFrame,
        risk_free_rate: float = 0.0,
        periods_per_year: int = 252 * 390,  # 1-min bars, ~390 per day
    ) -> float:
        """Calculate annualized Sharpe ratio."""
        returns = equity_df["equity"].pct_change().dropna()
        if len(returns) < 2:
            return 0.0

        excess_returns = returns - risk_free_rate / periods_per_year
        if excess_returns.std() == 0:
            return 0.0

        sharpe = (excess_returns.mean() / excess_returns.std()) * np.sqrt(periods_per_year)
        return sharpe
