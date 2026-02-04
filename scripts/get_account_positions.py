#!/usr/bin/env python3
"""
Get account positions from IBKR and export to CSV.

Extracts all position metrics by ticker including:
- Symbol, contract details
- Position size, average cost
- Market value, unrealized P&L
- Current price, daily P&L
"""

import csv
import sys
from datetime import datetime
from pathlib import Path

from ib_insync import IB

sys.path.insert(0, str(Path(__file__).parent.parent))
from ibkr.connection import IBKRConnection


def get_account_positions():
    """Connect to IBKR and retrieve all account positions."""
    print("Connecting to IBKR...")
    conn = IBKRConnection()
    ib = conn.connect()

    positions_data = []

    try:
        # Get account summary
        print("Fetching account summary...")
        account_values = ib.accountSummary()

        # Extract key account metrics
        account_metrics = {}
        for av in account_values:
            account_metrics[av.tag] = av.value

        print(f"Account: {account_metrics.get('Account', 'N/A')}")
        print(f"Net Liquidation: ${float(account_metrics.get('NetLiquidation', 0)):,.2f}")
        print(f"Available Funds: ${float(account_metrics.get('AvailableFunds', 0)):,.2f}")

        # Get all positions
        print("\nFetching positions...")
        portfolio = ib.portfolio()

        if not portfolio:
            print("No positions found in account.")
            return [], account_metrics

        print(f"Found {len(portfolio)} positions\n")

        for item in portfolio:
            contract = item.contract

            # Request market data for current price
            ib.qualifyContracts(contract)
            ticker = ib.reqMktData(contract, '', False, False)
            ib.sleep(1)  # Wait for data

            # Get current market price
            current_price = None
            if ticker.last and ticker.last > 0:
                current_price = ticker.last
            elif ticker.close and ticker.close > 0:
                current_price = ticker.close
            elif ticker.bid and ticker.ask:
                current_price = (ticker.bid + ticker.ask) / 2

            ib.cancelMktData(contract)

            # Calculate metrics
            position_data = {
                'symbol': contract.symbol,
                'local_symbol': contract.localSymbol or contract.symbol,
                'sec_type': contract.secType,
                'exchange': contract.exchange or contract.primaryExchange,
                'currency': contract.currency,
                'expiry': getattr(contract, 'lastTradeDateOrContractMonth', ''),
                'strike': getattr(contract, 'strike', ''),
                'right': getattr(contract, 'right', ''),
                'multiplier': contract.multiplier or 1,
                'position': item.position,
                'avg_cost': item.averageCost,
                'market_price': item.marketPrice,
                'market_value': item.marketValue,
                'unrealized_pnl': item.unrealizedPNL,
                'realized_pnl': item.realizedPNL,
                'current_price': current_price,
                'account': item.account,
            }

            # Calculate additional metrics
            if item.position != 0:
                position_data['cost_basis'] = item.averageCost * abs(item.position)
                if current_price and item.averageCost:
                    multiplier = float(contract.multiplier) if contract.multiplier else 1
                    if item.position > 0:
                        position_data['pnl_pct'] = ((current_price - item.averageCost / multiplier) / (item.averageCost / multiplier)) * 100
                    else:
                        position_data['pnl_pct'] = ((item.averageCost / multiplier - current_price) / (item.averageCost / multiplier)) * 100
                else:
                    position_data['pnl_pct'] = None
            else:
                position_data['cost_basis'] = 0
                position_data['pnl_pct'] = None

            positions_data.append(position_data)

            # Print summary
            print(f"  {position_data['local_symbol']:12} | "
                  f"Pos: {position_data['position']:>6} | "
                  f"Avg: ${position_data['avg_cost']:>10,.2f} | "
                  f"MktVal: ${position_data['market_value']:>12,.2f} | "
                  f"UnrealPnL: ${position_data['unrealized_pnl']:>10,.2f}")

    finally:
        ib.disconnect()
        print("\nDisconnected from IBKR")

    return positions_data, account_metrics


def export_to_csv(positions_data: list, account_metrics: dict, output_path: Path):
    """Export positions to CSV file."""
    if not positions_data:
        print("No positions to export.")
        return

    # Define CSV columns
    columns = [
        'symbol',
        'local_symbol',
        'sec_type',
        'exchange',
        'currency',
        'expiry',
        'strike',
        'right',
        'multiplier',
        'position',
        'avg_cost',
        'market_price',
        'current_price',
        'market_value',
        'cost_basis',
        'unrealized_pnl',
        'realized_pnl',
        'pnl_pct',
        'account',
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for pos in positions_data:
            writer.writerow({col: pos.get(col, '') for col in columns})

    print(f"\nPositions exported to: {output_path}")

    # Also export account summary
    account_csv = output_path.parent / "account_summary.csv"
    with open(account_csv, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['metric', 'value'])
        for key, value in sorted(account_metrics.items()):
            writer.writerow([key, value])

    print(f"Account summary exported to: {account_csv}")


def main():
    """Main entry point."""
    print("=" * 60)
    print("IBKR Account Positions Export")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60 + "\n")

    # Get positions
    positions_data, account_metrics = get_account_positions()

    # Export to CSV
    output_dir = Path(__file__).parent.parent / "data"
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_path = output_dir / f"positions_{timestamp}.csv"

    export_to_csv(positions_data, account_metrics, output_path)

    # Print summary
    if positions_data:
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"Total positions: {len(positions_data)}")
        total_market_value = sum(p['market_value'] for p in positions_data)
        total_unrealized = sum(p['unrealized_pnl'] for p in positions_data)
        print(f"Total market value: ${total_market_value:,.2f}")
        print(f"Total unrealized P&L: ${total_unrealized:,.2f}")


if __name__ == "__main__":
    main()
