"""
Performance Analytics and Reporting

Provides:
- Comprehensive performance metrics
- Drawdown analysis
- Trade analysis
- Visualization helpers
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import pandas as pd
import numpy as np


@dataclass
class PerformanceMetrics:
    """Comprehensive performance metrics."""
    # Returns
    total_return: float
    annualized_return: float
    monthly_returns: pd.Series

    # Risk
    volatility: float
    max_drawdown: float
    max_drawdown_duration: int  # in bars
    var_95: float  # Value at Risk 95%
    cvar_95: float  # Conditional VaR 95%

    # Risk-adjusted
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float

    # Trading
    total_trades: int
    win_rate: float
    profit_factor: float
    avg_trade_pnl: float
    avg_win: float
    avg_loss: float
    largest_win: float
    largest_loss: float
    avg_bars_held: float
    avg_bars_winning: float
    avg_bars_losing: float

    # Streaks
    max_consecutive_wins: int
    max_consecutive_losses: int

    # Exposure
    time_in_market: float  # percentage


class PerformanceAnalytics:
    """Calculate and report performance metrics."""

    def __init__(
        self,
        equity_curve: pd.DataFrame,
        trades: pd.DataFrame,
        initial_capital: float,
        risk_free_rate: float = 0.0,
        periods_per_year: int = 252 * 390,  # 1-min bars
    ):
        """
        Initialize analytics.

        Args:
            equity_curve: DataFrame with 'equity' column and datetime index
            trades: DataFrame with trade records
            initial_capital: Starting capital
            risk_free_rate: Annual risk-free rate
            periods_per_year: Number of periods per year for annualization
        """
        self.equity = equity_curve
        self.trades = trades
        self.initial_capital = initial_capital
        self.risk_free_rate = risk_free_rate
        self.periods_per_year = periods_per_year

        # Calculate returns
        self.returns = self.equity["equity"].pct_change().dropna()

    def calculate_metrics(self) -> PerformanceMetrics:
        """Calculate all performance metrics."""
        # Basic returns
        total_return = (
            self.equity["equity"].iloc[-1] / self.initial_capital - 1
        ) * 100

        # Annualized return
        n_periods = len(self.equity)
        years = n_periods / self.periods_per_year
        if years > 0:
            annualized_return = ((1 + total_return / 100) ** (1 / years) - 1) * 100
        else:
            annualized_return = 0

        # Monthly returns
        monthly_equity = self.equity["equity"].resample("ME").last()
        monthly_returns = monthly_equity.pct_change().dropna() * 100

        # Volatility (annualized)
        volatility = self.returns.std() * np.sqrt(self.periods_per_year) * 100

        # Drawdown analysis
        max_dd, max_dd_duration = self._calculate_drawdown()

        # VaR and CVaR
        var_95 = np.percentile(self.returns, 5) * 100
        cvar_95 = self.returns[self.returns <= np.percentile(self.returns, 5)].mean() * 100

        # Risk-adjusted metrics
        sharpe = self._calculate_sharpe()
        sortino = self._calculate_sortino()
        calmar = annualized_return / max_dd if max_dd > 0 else 0

        # Trade metrics
        trade_metrics = self._calculate_trade_metrics()

        # Time in market
        time_in_market = self._calculate_time_in_market()

        return PerformanceMetrics(
            total_return=total_return,
            annualized_return=annualized_return,
            monthly_returns=monthly_returns,
            volatility=volatility,
            max_drawdown=max_dd,
            max_drawdown_duration=max_dd_duration,
            var_95=var_95,
            cvar_95=cvar_95,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            time_in_market=time_in_market,
            **trade_metrics,
        )

    def _calculate_drawdown(self) -> tuple[float, int]:
        """Calculate maximum drawdown and duration."""
        equity = self.equity["equity"]
        peak = equity.expanding().max()
        drawdown = (equity - peak) / peak

        max_dd = abs(drawdown.min()) * 100

        # Duration of max drawdown
        in_drawdown = drawdown < 0
        drawdown_periods = []
        current_dd_start = None

        for i, (idx, is_dd) in enumerate(in_drawdown.items()):
            if is_dd and current_dd_start is None:
                current_dd_start = i
            elif not is_dd and current_dd_start is not None:
                drawdown_periods.append(i - current_dd_start)
                current_dd_start = None

        if current_dd_start is not None:
            drawdown_periods.append(len(in_drawdown) - current_dd_start)

        max_dd_duration = max(drawdown_periods) if drawdown_periods else 0

        return max_dd, max_dd_duration

    def _calculate_sharpe(self) -> float:
        """Calculate Sharpe ratio."""
        if self.returns.std() == 0:
            return 0

        excess_returns = self.returns - self.risk_free_rate / self.periods_per_year
        return (
            excess_returns.mean() / excess_returns.std() *
            np.sqrt(self.periods_per_year)
        )

    def _calculate_sortino(self) -> float:
        """Calculate Sortino ratio (uses downside deviation)."""
        excess_returns = self.returns - self.risk_free_rate / self.periods_per_year
        downside_returns = excess_returns[excess_returns < 0]

        if len(downside_returns) == 0 or downside_returns.std() == 0:
            return 0

        downside_std = downside_returns.std()
        return (
            excess_returns.mean() / downside_std *
            np.sqrt(self.periods_per_year)
        )

    def _calculate_trade_metrics(self) -> dict:
        """Calculate trade-related metrics."""
        if len(self.trades) == 0:
            return {
                "total_trades": 0,
                "win_rate": 0,
                "profit_factor": 0,
                "avg_trade_pnl": 0,
                "avg_win": 0,
                "avg_loss": 0,
                "largest_win": 0,
                "largest_loss": 0,
                "avg_bars_held": 0,
                "avg_bars_winning": 0,
                "avg_bars_losing": 0,
                "max_consecutive_wins": 0,
                "max_consecutive_losses": 0,
            }

        winners = self.trades[self.trades["pnl"] > 0]
        losers = self.trades[self.trades["pnl"] <= 0]

        total_trades = len(self.trades)
        win_rate = len(winners) / total_trades * 100

        gross_profit = winners["pnl"].sum() if len(winners) > 0 else 0
        gross_loss = abs(losers["pnl"].sum()) if len(losers) > 0 else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        avg_win = winners["pnl"].mean() if len(winners) > 0 else 0
        avg_loss = losers["pnl"].mean() if len(losers) > 0 else 0

        # Consecutive wins/losses
        is_winner = self.trades["pnl"] > 0
        max_wins, max_losses = self._calculate_streaks(is_winner)

        return {
            "total_trades": total_trades,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "avg_trade_pnl": self.trades["pnl"].mean(),
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "largest_win": winners["pnl"].max() if len(winners) > 0 else 0,
            "largest_loss": losers["pnl"].min() if len(losers) > 0 else 0,
            "avg_bars_held": self.trades["bars_held"].mean(),
            "avg_bars_winning": winners["bars_held"].mean() if len(winners) > 0 else 0,
            "avg_bars_losing": losers["bars_held"].mean() if len(losers) > 0 else 0,
            "max_consecutive_wins": max_wins,
            "max_consecutive_losses": max_losses,
        }

    def _calculate_streaks(self, is_winner: pd.Series) -> tuple[int, int]:
        """Calculate max consecutive wins and losses."""
        max_wins = 0
        max_losses = 0
        current_wins = 0
        current_losses = 0

        for won in is_winner:
            if won:
                current_wins += 1
                current_losses = 0
                max_wins = max(max_wins, current_wins)
            else:
                current_losses += 1
                current_wins = 0
                max_losses = max(max_losses, current_losses)

        return max_wins, max_losses

    def _calculate_time_in_market(self) -> float:
        """Calculate percentage of time in market."""
        # This is approximate - would need position tracking for accuracy
        if len(self.trades) == 0:
            return 0

        total_bars = len(self.equity)
        bars_in_trade = self.trades["bars_held"].sum()
        return (bars_in_trade / total_bars) * 100

    def print_report(self, metrics: Optional[PerformanceMetrics] = None):
        """Print formatted performance report."""
        if metrics is None:
            metrics = self.calculate_metrics()

        print("\n" + "=" * 60)
        print("BACKTEST PERFORMANCE REPORT")
        print("=" * 60)

        print("\n--- Returns ---")
        print(f"Total Return:        {metrics.total_return:>10.2f}%")
        print(f"Annualized Return:   {metrics.annualized_return:>10.2f}%")

        print("\n--- Risk Metrics ---")
        print(f"Volatility (Ann.):   {metrics.volatility:>10.2f}%")
        print(f"Max Drawdown:        {metrics.max_drawdown:>10.2f}%")
        print(f"Max DD Duration:     {metrics.max_drawdown_duration:>10,} bars")
        print(f"VaR (95%):           {metrics.var_95:>10.2f}%")
        print(f"CVaR (95%):          {metrics.cvar_95:>10.2f}%")

        print("\n--- Risk-Adjusted Returns ---")
        print(f"Sharpe Ratio:        {metrics.sharpe_ratio:>10.2f}")
        print(f"Sortino Ratio:       {metrics.sortino_ratio:>10.2f}")
        print(f"Calmar Ratio:        {metrics.calmar_ratio:>10.2f}")

        print("\n--- Trade Statistics ---")
        print(f"Total Trades:        {metrics.total_trades:>10}")
        print(f"Win Rate:            {metrics.win_rate:>10.1f}%")
        print(f"Profit Factor:       {metrics.profit_factor:>10.2f}")
        print(f"Avg Trade P&L:       ${metrics.avg_trade_pnl:>9,.2f}")
        print(f"Avg Win:             ${metrics.avg_win:>9,.2f}")
        print(f"Avg Loss:            ${metrics.avg_loss:>9,.2f}")
        print(f"Largest Win:         ${metrics.largest_win:>9,.2f}")
        print(f"Largest Loss:        ${metrics.largest_loss:>9,.2f}")

        print("\n--- Holding Periods ---")
        print(f"Avg Bars Held:       {metrics.avg_bars_held:>10.1f}")
        print(f"Avg Bars (Winners):  {metrics.avg_bars_winning:>10.1f}")
        print(f"Avg Bars (Losers):   {metrics.avg_bars_losing:>10.1f}")

        print("\n--- Streaks ---")
        print(f"Max Consec. Wins:    {metrics.max_consecutive_wins:>10}")
        print(f"Max Consec. Losses:  {metrics.max_consecutive_losses:>10}")

        print("\n--- Exposure ---")
        print(f"Time in Market:      {metrics.time_in_market:>10.1f}%")

        print("\n" + "=" * 60)

    def get_monthly_returns_table(self) -> pd.DataFrame:
        """Get monthly returns formatted as year x month table."""
        monthly = self.equity["equity"].resample("ME").last().pct_change() * 100

        # Create pivot table
        monthly_df = pd.DataFrame({
            "year": monthly.index.year,
            "month": monthly.index.month,
            "return": monthly.values,
        })

        pivot = monthly_df.pivot(index="year", columns="month", values="return")
        pivot.columns = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        # Add yearly total
        pivot["Year"] = pivot.sum(axis=1)

        return pivot

    def get_drawdown_periods(self, threshold: float = 5.0) -> pd.DataFrame:
        """Get significant drawdown periods."""
        equity = self.equity["equity"]
        peak = equity.expanding().max()
        drawdown = (equity - peak) / peak * 100

        # Find drawdown starts and ends
        periods = []
        in_drawdown = False
        start_idx = None
        peak_value = None

        for idx, (dd, eq, pk) in enumerate(zip(drawdown, equity, peak)):
            if abs(dd) >= threshold and not in_drawdown:
                in_drawdown = True
                start_idx = drawdown.index[idx]
                peak_value = pk
            elif dd == 0 and in_drawdown:
                periods.append({
                    "start": start_idx,
                    "end": drawdown.index[idx],
                    "peak_equity": peak_value,
                    "trough_equity": equity[start_idx:drawdown.index[idx]].min(),
                    "max_drawdown": abs(drawdown[start_idx:drawdown.index[idx]].min()),
                    "recovery_bars": idx - drawdown.index.get_loc(start_idx),
                })
                in_drawdown = False

        return pd.DataFrame(periods)
