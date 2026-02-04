"""
Get Historical Trades via IBKR Flex Query

Flex Queries allow retrieval of historical trade data that the real-time API cannot provide.

SETUP REQUIRED:
1. Log into IBKR Account Management (ibkr.com)
2. Go to: Reports → Flex Queries → Create New
3. Create a "Trade Confirmation Flex Query" with these fields:
   - AccountId, TradeDate, Symbol, Description
   - Buy/Sell, Quantity, TradePrice, Commission
   - NetCash, RealizedPnL, CostBasis
4. Set date period (e.g., last 7 days)
5. Get your Token and Query ID from the query settings

Usage:
    python get_trades_flex_query.py --token YOUR_TOKEN --query-id YOUR_QUERY_ID
"""

import argparse
import requests
import xml.etree.ElementTree as ET
import pandas as pd
from datetime import datetime
from pathlib import Path
import time

# IBKR Flex Query endpoints
FLEX_REQUEST_URL = "https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.SendRequest"
FLEX_DOWNLOAD_URL = "https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.GetStatement"


def request_flex_report(token: str, query_id: str) -> str:
    """Request a Flex Query report and get the reference code."""
    params = {
        't': token,
        'q': query_id,
        'v': '3'
    }

    print(f"Requesting Flex Query {query_id}...")
    response = requests.get(FLEX_REQUEST_URL, params=params)

    if response.status_code != 200:
        raise Exception(f"Request failed: {response.status_code}")

    # Parse XML response
    root = ET.fromstring(response.text)

    # Check for errors
    status = root.find('.//Status')
    if status is not None and status.text != 'Success':
        error_code = root.find('.//ErrorCode')
        error_msg = root.find('.//ErrorMessage')
        raise Exception(f"Flex Query Error {error_code.text if error_code is not None else 'unknown'}: {error_msg.text if error_msg is not None else 'unknown'}")

    # Get reference code
    ref_code = root.find('.//ReferenceCode')
    if ref_code is None:
        raise Exception("No reference code in response")

    return ref_code.text


def download_flex_report(token: str, ref_code: str, max_retries: int = 10) -> str:
    """Download the Flex Query report once it's ready."""
    params = {
        't': token,
        'q': ref_code,
        'v': '3'
    }

    for attempt in range(max_retries):
        print(f"Downloading report (attempt {attempt + 1}/{max_retries})...")
        response = requests.get(FLEX_DOWNLOAD_URL, params=params)

        if response.status_code != 200:
            raise Exception(f"Download failed: {response.status_code}")

        # Check if report is ready
        if 'FlexQueryResponse' in response.text or 'FlexStatements' in response.text:
            return response.text

        # Check for "please wait" status
        if 'Statement generation in progress' in response.text:
            print("  Report still generating, waiting 5 seconds...")
            time.sleep(5)
            continue

        # Unknown response
        print(f"  Unexpected response: {response.text[:200]}")
        time.sleep(3)

    raise Exception("Timeout waiting for report generation")


def parse_trades_xml(xml_content: str) -> pd.DataFrame:
    """Parse the Flex Query XML response into a DataFrame."""
    root = ET.fromstring(xml_content)

    trades = []

    # Find all trade confirmations
    for trade in root.findall('.//Trade') + root.findall('.//TradeConfirm'):
        trade_data = {}
        for key in ['accountId', 'tradeDate', 'symbol', 'description', 'buySell',
                    'quantity', 'tradePrice', 'commission', 'netCash', 'realizedPnL',
                    'costBasis', 'currency', 'assetCategory', 'underlyingSymbol',
                    'dateTime', 'exchange', 'orderType']:
            val = trade.get(key)
            if val:
                trade_data[key] = val

        if trade_data:
            trades.append(trade_data)

    if not trades:
        print("No trades found in response")
        return pd.DataFrame()

    df = pd.DataFrame(trades)

    # Convert numeric columns
    for col in ['quantity', 'tradePrice', 'commission', 'netCash', 'realizedPnL', 'costBasis']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # Sort by date
    if 'tradeDate' in df.columns:
        df = df.sort_values('tradeDate', ascending=False)
    elif 'dateTime' in df.columns:
        df = df.sort_values('dateTime', ascending=False)

    return df


def get_historical_trades(token: str, query_id: str, num_trades: int = 7):
    """Get historical trades via Flex Query."""
    try:
        # Request the report
        ref_code = request_flex_report(token, query_id)
        print(f"Reference code: {ref_code}")

        # Wait a moment for report generation
        time.sleep(2)

        # Download the report
        xml_content = download_flex_report(token, ref_code)

        # Parse into DataFrame
        df = parse_trades_xml(xml_content)

        if df.empty:
            print("No trades found")
            return None

        print(f"\n{'='*70}")
        print(f"LAST {min(num_trades, len(df))} TRADES")
        print(f"{'='*70}")

        total_pnl = 0
        total_commission = 0

        for _, row in df.head(num_trades).iterrows():
            date = row.get('tradeDate') or row.get('dateTime', 'Unknown')
            symbol = row.get('symbol', 'Unknown')
            side = row.get('buySell', '?')
            qty = row.get('quantity', 0)
            price = row.get('tradePrice', 0)
            comm = row.get('commission', 0)
            pnl = row.get('realizedPnL', 0)

            print(f"\n{date}")
            print(f"  {side} {qty} {symbol} @ ${price:.2f}")
            if comm:
                print(f"  Commission: ${abs(comm):.2f}")
                total_commission += abs(comm)
            if pnl:
                pnl_str = f"+${pnl:.2f}" if pnl > 0 else f"-${abs(pnl):.2f}"
                print(f"  Realized P&L: {pnl_str}")
                total_pnl += pnl

        print(f"\n{'='*70}")
        print(f"SUMMARY")
        print(f"{'='*70}")
        print(f"Total Trades: {len(df)}")
        print(f"Total Commission: ${total_commission:.2f}")
        print(f"Total Realized P&L: ${total_pnl:.2f}")

        # Export
        output_dir = Path(__file__).parent.parent / "data"
        output_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = output_dir / f"trades_flex_{timestamp}.csv"
        df.to_csv(output_file, index=False)
        print(f"\nExported to: {output_file}")

        return df

    except Exception as e:
        print(f"Error: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description='Get historical trades via IBKR Flex Query')
    parser.add_argument('--token', '-t', required=True, help='Flex Query token')
    parser.add_argument('--query-id', '-q', required=True, help='Flex Query ID')
    parser.add_argument('--num-trades', '-n', type=int, default=7, help='Number of trades to show')

    args = parser.parse_args()

    get_historical_trades(args.token, args.query_id, args.num_trades)


if __name__ == "__main__":
    print("""
IBKR Flex Query Trade Retrieval
===============================

This script retrieves historical trades using IBKR Flex Queries.

SETUP (one-time):
1. Log into ibkr.com → Account Management
2. Go to: Reports → Flex Queries
3. Click "Create" or "+" to add a new query
4. Select "Trade Confirmation Flex Query"
5. Configure the fields you want (Symbol, Date, Price, P&L, etc.)
6. Save the query
7. Note your Query ID and Token

USAGE:
    python get_trades_flex_query.py --token YOUR_TOKEN --query-id YOUR_QUERY_ID

Example:
    python get_trades_flex_query.py -t 123456789 -q 987654
""")

    # Check if running with arguments
    import sys
    if len(sys.argv) > 1:
        main()
