"""
Get Account Positions with Complete Price Data

Handles both real-time and frozen (last available) prices.
Uses IB Gateway port 4001.
"""

from ib_insync import IB, Stock, Future, Option, Contract, util
import pandas as pd
from datetime import datetime
from pathlib import Path
import time

def get_positions_complete():
    """Get positions with best available price data."""
    ib = IB()

    try:
        # Connect to IB Gateway (port 4001)
        ib.connect('127.0.0.1', 4001, clientId=30)
        print("Connected to IB Gateway")

        # First try real-time, then fall back to frozen for closed markets
        # Type 1 = Live, Type 2 = Frozen (last available when market closed)
        ib.reqMarketDataType(4)  # 4 = Delayed Frozen (best fallback)
        print("Market data type: Delayed Frozen (will use last available price if market closed)")

        # Get all positions
        positions = ib.positions()
        print(f"\nFound {len(positions)} positions")

        if not positions:
            print("No positions found")
            return None

        # Get portfolio data which includes market values
        portfolio_items = ib.portfolio()
        portfolio_dict = {}
        for item in portfolio_items:
            key = (item.account, item.contract.conId)
            portfolio_dict[key] = item

        position_data = []
        errors = []

        for i, pos in enumerate(positions):
            contract = pos.contract
            print(f"\n[{i+1}/{len(positions)}] {contract.symbol} ({contract.secType})", end="")

            row = {
                'account': pos.account,
                'symbol': contract.symbol,
                'localSymbol': contract.localSymbol or contract.symbol,
                'secType': contract.secType,
                'exchange': contract.exchange or contract.primaryExchange,
                'currency': contract.currency,
                'position': pos.position,
                'avgCost': pos.avgCost,
                'marketPrice': None,
                'marketValue': None,
                'unrealizedPnL': None,
                'unrealizedPnLPct': None,
                'lastUpdated': None,
                'priceSource': None,
            }

            # Try to get data from portfolio first (most reliable)
            key = (pos.account, contract.conId)
            if key in portfolio_dict:
                pf = portfolio_dict[key]
                row['marketPrice'] = pf.marketPrice
                row['marketValue'] = pf.marketValue
                row['unrealizedPnL'] = pf.unrealizedPNL
                if pf.averageCost and pf.averageCost != 0:
                    cost_basis = pf.averageCost * abs(pos.position)
                    if cost_basis != 0:
                        row['unrealizedPnLPct'] = (pf.unrealizedPNL / cost_basis) * 100
                row['priceSource'] = 'portfolio'
                print(f" - portfolio: ${pf.marketPrice:.2f}" if pf.marketPrice else " - portfolio: no price")

            # If no price from portfolio, try market data request
            if row['marketPrice'] is None or row['marketPrice'] <= 0:
                try:
                    # Qualify the contract
                    qualified = None

                    if contract.secType == 'STK':
                        qualified = Stock(contract.symbol, 'SMART', contract.currency)
                    elif contract.secType == 'FUT':
                        qualified = Future(conId=contract.conId)
                    elif contract.secType == 'OPT':
                        qualified = Option(conId=contract.conId)
                    else:
                        qualified = Contract(conId=contract.conId)

                    if qualified:
                        ib.qualifyContracts(qualified)
                        ticker = ib.reqMktData(qualified, '', False, False)
                        ib.sleep(2)  # Wait for data

                        price = None
                        source = None

                        # Try different price fields
                        if ticker.last and ticker.last > 0:
                            price = ticker.last
                            source = 'last'
                        elif ticker.close and ticker.close > 0:
                            price = ticker.close
                            source = 'close'
                        elif ticker.bid and ticker.bid > 0 and ticker.ask and ticker.ask > 0:
                            price = (ticker.bid + ticker.ask) / 2
                            source = 'mid'
                        elif ticker.bid and ticker.bid > 0:
                            price = ticker.bid
                            source = 'bid'

                        if price:
                            row['marketPrice'] = price
                            row['priceSource'] = source

                            # Calculate market value and PnL
                            multiplier = float(contract.multiplier) if contract.multiplier else 1.0
                            row['marketValue'] = price * pos.position * multiplier
                            cost_basis = pos.avgCost * pos.position
                            row['unrealizedPnL'] = row['marketValue'] - cost_basis
                            if cost_basis != 0:
                                row['unrealizedPnLPct'] = (row['unrealizedPnL'] / cost_basis) * 100

                            print(f" - {source}: ${price:.2f}")
                        else:
                            print(f" - no price available")

                        ib.cancelMktData(qualified)

                except Exception as e:
                    error_msg = str(e)
                    if "10089" in error_msg:
                        errors.append(f"{contract.symbol}: API subscription required")
                    elif "200" in error_msg:
                        errors.append(f"{contract.symbol}: No security definition")
                    else:
                        errors.append(f"{contract.symbol}: {error_msg[:50]}")
                    print(f" - error")

            row['lastUpdated'] = datetime.now().isoformat()
            position_data.append(row)

        # Create DataFrame
        df = pd.DataFrame(position_data)

        # Sort by account, then by market value (descending)
        df['abs_value'] = df['marketValue'].abs().fillna(0)
        df = df.sort_values(['account', 'abs_value'], ascending=[True, False])
        df = df.drop('abs_value', axis=1)

        # Summary stats
        print("\n" + "="*60)
        print("SUMMARY")
        print("="*60)

        for account in df['account'].unique():
            acct_df = df[df['account'] == account]
            total_value = acct_df['marketValue'].sum()
            total_pnl = acct_df['unrealizedPnL'].sum()
            positions_with_price = acct_df['marketPrice'].notna().sum()
            print(f"\nAccount: {account}")
            print(f"  Positions: {len(acct_df)} ({positions_with_price} with prices)")
            print(f"  Total Market Value: ${total_value:,.2f}" if pd.notna(total_value) else "  Total Market Value: N/A")
            print(f"  Unrealized P&L: ${total_pnl:,.2f}" if pd.notna(total_pnl) else "  Unrealized P&L: N/A")

        # Export to CSV
        output_dir = Path(__file__).parent.parent / "data"
        output_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = output_dir / f"positions_complete_{timestamp}.csv"
        df.to_csv(output_file, index=False)
        print(f"\nExported to: {output_file}")

        # Print errors summary
        if errors:
            print(f"\n{len(errors)} symbols had errors (likely no market data subscription)")

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
    df = get_positions_complete()

    if df is not None:
        # Show positions with prices
        print("\n" + "="*60)
        print("POSITIONS WITH PRICES")
        print("="*60)

        cols = ['symbol', 'secType', 'position', 'avgCost', 'marketPrice', 'marketValue', 'unrealizedPnL', 'priceSource']
        priced = df[df['marketPrice'].notna()][cols]
        if len(priced) > 0:
            print(priced.to_string(index=False))

        # Show positions without prices
        no_price = df[df['marketPrice'].isna()]
        if len(no_price) > 0:
            print(f"\n{len(no_price)} positions without prices:")
            print(no_price[['symbol', 'secType', 'position', 'avgCost']].to_string(index=False))
