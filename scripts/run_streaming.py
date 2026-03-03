#!/usr/bin/env python3
"""
Real-Time Streaming Dashboard for IBKR Futures

Displays a continuously-refreshing console dashboard with:
- Market data table (price, change, spread, session range, IV)
- Portfolio table (positions, P&L)
- Portfolio summary (total value, P&L)

Usage:
    python scripts/run_streaming.py
    python scripts/run_streaming.py --symbols ES GC SI NQ CL
    python scripts/run_streaming.py --symbols ES GC --refresh 5 --no-portfolio
"""

import argparse
import os
import signal
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ibkr.connection import IBKRConnection
from ibkr.streaming import MarketStreamer


def clear_screen():
    """Clear the terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


def fmt_price(value, decimals=2):
    """Format a price value for display."""
    if value is None:
        return "---"
    return f"{value:,.{decimals}f}"


def fmt_change(change, change_pct):
    """Format change with sign and percentage."""
    if change is None or change_pct is None:
        return "---", "---"
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:,.2f}", f"{sign}{change_pct:.2f}%"


def fmt_pnl(value):
    """Format P&L value with sign."""
    if value is None:
        return "---"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:,.2f}"


def render_dashboard(streamer, include_portfolio=True):
    """Render the streaming dashboard to the terminal."""
    clear_screen()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    width = 120

    print("=" * width)
    print(f"  IBKR FUTURES STREAMING DASHBOARD  |  {now}")
    print("=" * width)

    # --- Market Data Table ---
    quotes = streamer.get_quotes()

    if quotes:
        print()
        print("  MARKET DATA")
        print("  " + "-" * (width - 4))

        header = (
            f"  {'Symbol':<8} {'Last':>10} {'Change':>10} {'Chg%':>8} "
            f"{'Bid':>10} {'Ask':>10} {'Spread':>8} "
            f"{'Sess H':>10} {'Sess L':>10} {'Volume':>10} {'IV':>8}"
        )
        print(header)
        print("  " + "-" * (width - 4))

        for symbol in sorted(quotes.keys()):
            q = quotes[symbol]
            chg_str, chg_pct_str = fmt_change(q.change, q.change_pct)

            iv_str = "---"
            if q.implied_volatility is not None:
                iv_str = f"{q.implied_volatility * 100:.1f}%"

            spread_str = fmt_price(q.spread, 2)
            vol_str = f"{q.volume:,}" if q.volume else "---"

            row = (
                f"  {symbol:<8} {fmt_price(q.last):>10} {chg_str:>10} {chg_pct_str:>8} "
                f"{fmt_price(q.bid):>10} {fmt_price(q.ask):>10} {spread_str:>8} "
                f"{fmt_price(q.session_high):>10} {fmt_price(q.session_low):>10} "
                f"{vol_str:>10} {iv_str:>8}"
            )
            print(row)

        print("  " + "-" * (width - 4))

        # Tick counts and last update age
        update_parts = []
        for symbol in sorted(quotes.keys()):
            q = quotes[symbol]
            age = ""
            if q.last_update:
                secs = (datetime.now() - q.last_update).total_seconds()
                age = f"{secs:.0f}s ago"
            update_parts.append(f"{symbol}: {q.tick_count} ticks ({age})")
        print(f"  Updates: {' | '.join(update_parts)}")

    # --- Portfolio Table ---
    if include_portfolio:
        summary, positions = streamer.get_portfolio()

        print()
        print("  PORTFOLIO")
        print("  " + "-" * (width - 20))

        if positions:
            pf_header = (
                f"  {'Symbol':<10} {'Pos':>8} {'Avg Cost':>12} {'Mkt Price':>12} "
                f"{'Mkt Value':>14} {'Unreal P&L':>12} {'P&L%':>8}"
            )
            print(pf_header)
            print("  " + "-" * (width - 20))

            for pos in positions:
                pnl_pct_str = f"{pos.pnl_pct:.2f}%" if pos.pnl_pct is not None else "---"

                row = (
                    f"  {pos.local_symbol or pos.symbol:<10} "
                    f"{pos.position_size:>8.0f} "
                    f"${fmt_price(pos.avg_cost):>11} "
                    f"${fmt_price(pos.market_price):>11} "
                    f"${fmt_price(pos.market_value):>13} "
                    f"${fmt_pnl(pos.unrealized_pnl):>11} "
                    f"{pnl_pct_str:>8}"
                )
                print(row)

            print("  " + "-" * (width - 20))
        else:
            print("  No positions found")
            print("  " + "-" * (width - 20))

        # Portfolio Summary
        print()
        print("  PORTFOLIO SUMMARY")
        print(f"    Positions:       {summary.position_count}")
        if summary.net_liquidation is not None:
            print(f"    Net Liquidation: ${summary.net_liquidation:>14,.2f}")
        print(f"    Total Mkt Value: ${summary.total_market_value:>14,.2f}")
        print(f"    Unrealized P&L:  ${fmt_pnl(summary.total_unrealized_pnl):>14}")
        print(f"    Realized P&L:    ${fmt_pnl(summary.total_realized_pnl):>14}")
        if summary.available_funds is not None:
            print(f"    Available Funds: ${summary.available_funds:>14,.2f}")
        if summary.last_update:
            age = (datetime.now() - summary.last_update).total_seconds()
            print(f"    Last Refresh:    {age:.0f}s ago")

    print()
    print("  Press Ctrl+C to stop")
    print("=" * width)


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="IBKR Real-Time Streaming Dashboard"
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["ES", "GC", "SI"],
        help="Futures symbols to stream (default: ES GC SI)",
    )
    parser.add_argument(
        "--refresh",
        type=float,
        default=2.0,
        help="Dashboard refresh interval in seconds (default: 2.0)",
    )
    parser.add_argument(
        "--portfolio-refresh",
        type=float,
        default=30.0,
        help="Portfolio data refresh interval in seconds (default: 30.0)",
    )
    parser.add_argument(
        "--no-portfolio",
        action="store_true",
        help="Disable portfolio monitoring",
    )
    return parser.parse_args()


def main():
    """Main entry point for the streaming dashboard."""
    args = parse_args()

    print("=" * 60)
    print("IBKR STREAMING DASHBOARD")
    print(f"Symbols: {', '.join(args.symbols)}")
    portfolio_status = "OFF" if args.no_portfolio else f"ON ({args.portfolio_refresh}s)"
    print(f"Refresh: {args.refresh}s | Portfolio: {portfolio_status}")
    print("=" * 60)
    print()

    # Graceful shutdown
    running = True

    def signal_handler(sig, frame):
        nonlocal running
        print("\n\nShutting down...")
        running = False

    signal.signal(signal.SIGINT, signal_handler)

    conn = IBKRConnection()

    with conn.session() as ib:
        streamer = MarketStreamer(
            ib,
            symbols=args.symbols,
            include_portfolio=not args.no_portfolio,
            portfolio_refresh_interval=args.portfolio_refresh,
        )

        streamer.start()
        print("Streaming started. Waiting for data...\n")

        last_render = 0

        while running:
            ib.sleep(0.1)
            streamer.tick()

            now_ts = datetime.now().timestamp()
            if now_ts - last_render >= args.refresh:
                render_dashboard(
                    streamer,
                    include_portfolio=not args.no_portfolio,
                )
                last_render = now_ts

        streamer.stop()
        print("\nStreaming stopped.")


if __name__ == "__main__":
    main()
