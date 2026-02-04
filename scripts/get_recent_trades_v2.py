"""
Get Recent Trades and Realized P&L from IBKR - Version 2

Uses multiple methods to find trade history:
1. reqExecutions() - Current session fills
2. reqCompletedOrders() - Recently completed orders
3. Portfolio unrealized P&L for reference

Uses IB Gateway port 4001.

NOTE: This script only requires READ-ONLY API access.
All methods used (reqExecutions, fills, trades, openOrders) are read-only operations.
The "Read-Only mode" warning is expected and does not affect this script.
"""

from ib_insync import IB, ExecutionFilter, util
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

def get_recent_trades():
    """Get recent trades with realized P&L using multiple methods."""
    ib = IB()

    try:
        # Connect to IB Gateway (port 4001)
        ib.connect('127.0.0.1', 4001, clientId=32)
        print("Connected to IB Gateway")

        all_trades = []

        # Method 1: Get executions with a filter for recent days
        print("\n--- Checking Executions ---")
        # Create execution filter for last 7 days
        exec_filter = ExecutionFilter()
        # Note: IBKR typically only returns same-day executions via API

        executions = ib.reqExecutions(exec_filter)
        ib.sleep(2)  # Wait for response

        print(f"Executions found: {len(executions)}")
        for exec_fill in executions:
            print(f"  {exec_fill.execution.time} - {exec_fill.execution.side} {exec_fill.execution.shares} {exec_fill.contract.symbol}")

        # Method 2: Get all fills
        print("\n--- Checking Fills ---")
        fills = ib.fills()
        print(f"Fills found: {len(fills)}")

        for fill in fills:
            exec_data = fill.execution
            contract = fill.contract
            comm = fill.commissionReport

            trade_info = {
                'time': exec_data.time,
                'symbol': contract.symbol,
                'localSymbol': contract.localSymbol or contract.symbol,
                'secType': contract.secType,
                'side': exec_data.side,
                'quantity': exec_data.shares,
                'price': exec_data.price,
                'avgPrice': exec_data.avgPrice,
                'exchange': exec_data.exchange,
                'commission': comm.commission if comm else 0,
                'realizedPnL': comm.realizedPNL if comm else 0,
                'currency': contract.currency,
                'source': 'fill'
            }
            all_trades.append(trade_info)
            print(f"  {trade_info['time']} - {trade_info['side']} {trade_info['quantity']} {trade_info['symbol']} @ ${trade_info['price']:.2f}")

        # Method 3: Check trades() which includes order info
        print("\n--- Checking Trades (Orders) ---")
        trades = ib.trades()
        print(f"Trade orders found: {len(trades)}")

        for trade in trades:
            if trade.fills:
                for fill in trade.fills:
                    print(f"  {fill.execution.time} - {fill.execution.side} {fill.execution.shares} {trade.contract.symbol}")

        # Method 4: Request completed orders (may have more history)
        print("\n--- Checking Completed Orders ---")
        # Note: This requires the orders to be fetched first
        # completedOrders are typically orders that filled today

        # Get open orders first (this populates internal state)
        open_orders = ib.openOrders()
        print(f"Open orders: {len(open_orders)}")

        # Now check all orders
        all_orders = ib.orders()
        print(f"All orders in session: {len(all_orders)}")

        # Summary
        print("\n" + "="*70)
        print("SUMMARY")
        print("="*70)

        if all_trades:
            df = pd.DataFrame(all_trades)
            df = df.sort_values('time', ascending=False)

            print(f"\nFound {len(df)} trades:")
            for _, row in df.head(7).iterrows():
                pnl_str = ""
                if row['realizedPnL'] and row['realizedPnL'] != 0:
                    pnl_str = f" | P&L: ${row['realizedPnL']:.2f}"
                print(f"  {row['time']} | {row['side']} {row['quantity']} {row['symbol']} @ ${row['price']:.2f}{pnl_str}")

            # Export
            output_dir = Path(__file__).parent.parent / "data"
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = output_dir / f"recent_trades_{timestamp}.csv"
            df.to_csv(output_file, index=False)
            print(f"\nExported to: {output_file}")

            return df
        else:
            print("\nNo trades found in current session.")
            print("\n" + "="*70)
            print("HOW TO GET HISTORICAL TRADES")
            print("="*70)
            print("""
IBKR API Limitation:
- reqExecutions() only returns executions from the CURRENT trading day
- Historical trades require Flex Queries or Account Management

Options for Historical Trade Data:

1. FLEX QUERIES (Recommended for automation):
   - Log into Account Management (ibkr.com)
   - Go to: Reports → Flex Queries → Create New
   - Select "Trade Confirmation Flex Query"
   - Configure fields: Date, Symbol, Side, Quantity, Price, Commission, P&L
   - Set delivery method: Download or API
   - Use the Flex Query Token with reqFlexQuery() API call

2. ACTIVITY STATEMENTS:
   - Account Management → Reports → Statements
   - Select "Activity" statement
   - Choose date range
   - Download as CSV/PDF

3. TRADE CONFIRMATIONS:
   - Account Management → Reports → Trade Confirmations
   - Shows individual trade details with P&L

4. TWS (Trader Workstation):
   - Account → Trade Log (shows today's trades)
   - Account → Portfolio → Right-click → Trade History
""")
            return None

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        ib.disconnect()
        print("\nDisconnected from IB Gateway")


if __name__ == "__main__":
    get_recent_trades()
