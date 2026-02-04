"""
Get Account Positions with Delayed Market Data

Uses delayed (15-min) market data to avoid API subscription requirements.
"""

from ib_insync import IB, Stock, util
import pandas as pd
from datetime import datetime
from pathlib import Path
import time

def get_positions_with_delayed_data():
    """Get positions using delayed market data."""
    ib = IB()

    try:
        ib.connect('127.0.0.1', 7496, clientId=20)
        print("Connected to TWS")

        # Request delayed market data (type 3)
        ib.reqMarketDataType(3)
        print("Switched to DELAYED market data (15-min delay)")

        # Get all positions
        positions = ib.positions()
        print(f"\nFound {len(positions)} positions")

        if not positions:
            print("No positions found")
            return None

        # Build position data
        position_data = []

        for pos in positions:
            contract = pos.contract

            row = {
                'account': pos.account,
                'symbol': contract.symbol,
                'secType': contract.secType,
                'exchange': contract.exchange or contract.primaryExchange,
                'currency': contract.currency,
                'position': pos.position,
                'avgCost': pos.avgCost,
                'marketPrice': None,
                'marketValue': None,
                'unrealizedPnL': None,
                'unrealizedPnLPct': None,
            }

            # Try to get market data for stocks
            if contract.secType == 'STK' and contract.currency == 'USD':
                try:
                    # Create qualified contract
                    stock = Stock(contract.symbol, 'SMART', 'USD')
                    ib.qualifyContracts(stock)

                    # Request ticker with delayed data
                    ticker = ib.reqMktData(stock, '', False, False)
                    ib.sleep(2)  # Wait for data

                    # Get delayed price (field 68 = delayed last)
                    if ticker.last and ticker.last > 0:
                        row['marketPrice'] = ticker.last
                    elif ticker.close and ticker.close > 0:
                        row['marketPrice'] = ticker.close
                    elif ticker.bid and ticker.bid > 0:
                        row['marketPrice'] = (ticker.bid + ticker.ask) / 2 if ticker.ask else ticker.bid

                    if row['marketPrice']:
                        row['marketValue'] = row['marketPrice'] * pos.position
                        cost_basis = pos.avgCost * pos.position
                        row['unrealizedPnL'] = row['marketValue'] - cost_basis
                        if cost_basis != 0:
                            row['unrealizedPnLPct'] = (row['unrealizedPnL'] / cost_basis) * 100

                    ib.cancelMktData(stock)

                except Exception as e:
                    print(f"  Error getting data for {contract.symbol}: {e}")

            position_data.append(row)
            print(f"  {contract.symbol}: pos={pos.position}, avgCost=${pos.avgCost:.2f}, price=${row['marketPrice'] or 'N/A'}")

        # Create DataFrame
        df = pd.DataFrame(position_data)

        # Export to CSV
        output_dir = Path(__file__).parent.parent / "data"
        output_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = output_dir / f"positions_delayed_{timestamp}.csv"
        df.to_csv(output_file, index=False)
        print(f"\nExported to: {output_file}")

        return df

    except Exception as e:
        print(f"Error: {e}")
        return None
    finally:
        ib.disconnect()
        print("\nDisconnected from TWS")


if __name__ == "__main__":
    df = get_positions_with_delayed_data()
    if df is not None:
        print(f"\nTotal positions: {len(df)}")
