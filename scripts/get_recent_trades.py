"""
Get Recent Trades and Realized P&L from IBKR

Extracts execution history with realized P&L.
Uses IB Gateway port 4001.

NOTE: This script only requires READ-ONLY API access.
All methods used (reqExecutions, fills, trades) are read-only operations.
The "Read-Only mode" warning is expected and does not affect this script.
"""

from ib_insync import IB, util
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

def get_recent_trades(num_trades: int = 7):
    """Get recent trades with realized P&L."""
    ib = IB()

    try:
        # Connect to IB Gateway (port 4001)
        ib.connect('127.0.0.1', 4001, clientId=31)
        print("Connected to IB Gateway")

        # Request executions (trades) - gets recent fills
        # Empty filter gets all recent executions
        executions = ib.reqExecutions()
        print(f"Found {len(executions)} recent executions")

        # Also get completed orders for more context
        trades = ib.trades()
        print(f"Found {len(trades)} trades in session")

        # Request all fills
        fills = ib.fills()
        print(f"Found {len(fills)} fills")

        if not fills:
            print("\nNo fills found in current session.")
            print("Note: IBKR only returns executions from the current trading day.")
            print("For historical trades, check Account Management or Flex Queries.")
            return None

        # Build trade data from fills
        trade_data = []
        for fill in fills:
            exec_data = fill.execution
            contract = fill.contract
            comm = fill.commissionReport

            row = {
                'execId': exec_data.execId,
                'time': exec_data.time,
                'symbol': contract.symbol,
                'localSymbol': contract.localSymbol or contract.symbol,
                'secType': contract.secType,
                'side': exec_data.side,
                'quantity': exec_data.shares,
                'price': exec_data.price,
                'avgPrice': exec_data.avgPrice,
                'exchange': exec_data.exchange,
                'orderId': exec_data.orderId,
                'commission': comm.commission if comm else None,
                'realizedPnL': comm.realizedPNL if comm else None,
                'currency': contract.currency,
            }
            trade_data.append(row)

        # Create DataFrame and sort by time
        df = pd.DataFrame(trade_data)
        df = df.sort_values('time', ascending=False)

        # Get the most recent trades
        df_recent = df.head(num_trades)

        print(f"\n{'='*70}")
        print(f"LAST {min(num_trades, len(df_recent))} TRADES")
        print(f"{'='*70}")

        total_realized_pnl = 0
        total_commission = 0

        for i, row in df_recent.iterrows():
            print(f"\n{row['time']}")
            print(f"  {row['side']} {row['quantity']} {row['symbol']} ({row['secType']}) @ ${row['price']:.2f}")
            print(f"  Exchange: {row['exchange']}")
            if row['commission']:
                print(f"  Commission: ${row['commission']:.2f}")
                total_commission += row['commission']
            if row['realizedPnL'] and row['realizedPnL'] != 0:
                pnl_str = f"+${row['realizedPnL']:.2f}" if row['realizedPnL'] > 0 else f"-${abs(row['realizedPnL']):.2f}"
                print(f"  Realized P&L: {pnl_str}")
                total_realized_pnl += row['realizedPnL']

        print(f"\n{'='*70}")
        print(f"SUMMARY")
        print(f"{'='*70}")
        print(f"Total Trades Shown: {len(df_recent)}")
        print(f"Total Commission: ${total_commission:.2f}")
        print(f"Total Realized P&L: ${total_realized_pnl:.2f}")

        # Export to CSV
        output_dir = Path(__file__).parent.parent / "data"
        output_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = output_dir / f"recent_trades_{timestamp}.csv"
        df.to_csv(output_file, index=False)
        print(f"\nAll {len(df)} trades exported to: {output_file}")

        return df

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        ib.disconnect()
        print("\nDisconnected from IB Gateway")


if __name__ == "__main__":
    df = get_recent_trades(num_trades=7)
