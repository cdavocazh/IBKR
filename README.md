# IBKR Market Data Framework

A Python framework for fetching market prices from Interactive Brokers (IBKR) using the `ib_insync` library.

## Features

- Simple connection management to TWS/IB Gateway
- Pre-defined contracts for common futures (metals, treasuries, indices, energy)
- Real-time quotes and streaming
- Historical data retrieval
- Pandas DataFrame integration

## Supported Instruments

### Precious Metals (COMEX/NYMEX)
- **GC** - Gold Futures
- **SI** - Silver Futures
- **MGC** - Micro Gold Futures
- **SIL** - Micro Silver Futures
- **HG** - Copper Futures
- **PL** - Platinum Futures
- **PA** - Palladium Futures

### Treasury Futures (CBOT)
- **ZN** - 10-Year T-Note Futures
- **ZB** - 30-Year T-Bond Futures
- **ZF** - 5-Year T-Note Futures
- **ZT** - 2-Year T-Note Futures
- **UB** - Ultra T-Bond Futures

### Equity Index Futures (CME/CBOT)
- **ES** - E-mini S&P 500
- **NQ** - E-mini Nasdaq 100
- **YM** - E-mini Dow
- **RTY** - E-mini Russell 2000
- **MES/MNQ/MYM/M2K** - Micro versions

### Energy Futures (NYMEX)
- **CL** - Crude Oil
- **NG** - Natural Gas
- **MCL** - Micro Crude Oil

## Installation

```bash
pip install -r requirements.txt
```

## Configuration

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

Default ports:
- **7497** - TWS Paper Trading
- **7496** - TWS Live Trading
- **4002** - IB Gateway Paper Trading
- **4001** - IB Gateway Live Trading

## Prerequisites

1. Install TWS (Trader Workstation) or IB Gateway
2. Enable API connections in TWS: Configure → API → Settings
   - Enable "Enable ActiveX and Socket Clients"
   - Set the Socket port (default 7497 for paper)
   - Add 127.0.0.1 to trusted IPs
3. Make sure TWS/Gateway is running before using scripts

## Usage

### Quick Start

```python
from ibkr import IBKRConnection, ContractFactory, MarketDataService

# Connect and get gold price
conn = IBKRConnection()

with conn.session() as ib:
    mds = MarketDataService(ib)

    # Get Gold futures quote
    gold = ContractFactory.gold_future()
    quote = mds.get_quote(gold)

    print(f"Gold: ${quote.last:,.2f}")
```

### Get Precious Metals Prices

```python
from ibkr import IBKRConnection, ContractFactory, MarketDataService

conn = IBKRConnection()

with conn.session() as ib:
    mds = MarketDataService(ib)

    gold = ContractFactory.gold_future()
    silver = ContractFactory.silver_future()

    gold_quote = mds.get_quote(gold)
    silver_quote = mds.get_quote(silver)

    print(f"Gold:   ${gold_quote.last:,.2f}")
    print(f"Silver: ${silver_quote.last:,.2f}")
```

### Get Treasury Futures

```python
from ibkr import IBKRConnection, ContractFactory, MarketDataService

conn = IBKRConnection()

with conn.session() as ib:
    mds = MarketDataService(ib)

    ten_year = ContractFactory.ten_year_note_future()
    quote = mds.get_quote(ten_year)

    print(f"10-Year Note: {quote.last:.4f}")
```

### Historical Data

```python
from ibkr import IBKRConnection, ContractFactory, MarketDataService

conn = IBKRConnection()

with conn.session() as ib:
    mds = MarketDataService(ib)

    gold = ContractFactory.gold_future()

    # Get daily bars for the last month
    df = mds.get_historical_bars(
        gold,
        duration="1 M",
        bar_size="1 day",
        what_to_show="TRADES"
    )

    print(df)
```

### Create Custom Futures Contract

```python
from ibkr import ContractFactory

# Create a specific expiry contract
gold_dec = ContractFactory.create_future("GC", expiry="202512")

# Create any futures contract
contract = ContractFactory.create_future(
    symbol="ES",
    expiry="202503",
    exchange="CME",
    currency="USD"
)
```

## Example Scripts

Run from the `examples` directory:

```bash
# Get Silver and Gold prices
python examples/get_precious_metals.py

# Get Treasury futures prices
python examples/get_treasury_futures.py

# Get multiple instruments at once
python examples/get_multiple_instruments.py

# Get historical data
python examples/get_historical_data.py

# Stream live prices
python examples/stream_prices.py
```

## Project Structure

```
IBKR/
├── ibkr/
│   ├── __init__.py          # Package exports
│   ├── connection.py         # IBKR connection manager
│   ├── contracts.py          # Contract factory and definitions
│   └── market_data.py        # Market data service
├── examples/
│   ├── get_precious_metals.py
│   ├── get_treasury_futures.py
│   ├── get_multiple_instruments.py
│   ├── get_historical_data.py
│   └── stream_prices.py
├── requirements.txt
├── .env.example
└── README.md
```

## API Reference

### IBKRConnection

```python
conn = IBKRConnection(host="127.0.0.1", port=7497, client_id=1)

# Context manager usage
with conn.session() as ib:
    # ib is the connected IB instance
    pass

# Manual connection
conn.connect()
conn.disconnect()
```

### ContractFactory

```python
# Pre-built contracts
gold = ContractFactory.gold_future()
silver = ContractFactory.silver_future()
ten_year = ContractFactory.ten_year_note_future()
sp500 = ContractFactory.sp500_future()

# Generic futures
contract = ContractFactory.create_future("GC", expiry="202502")

# List all available specs
specs = ContractFactory.list_available_contracts()
```

### MarketDataService

```python
mds = MarketDataService(ib)

# Get single quote
quote = mds.get_quote(contract)

# Get multiple quotes
quotes = mds.get_quotes([contract1, contract2])

# Historical data
df = mds.get_historical_bars(contract, duration="1 M", bar_size="1 day")

# Streaming
ticker = mds.stream_quotes(contract, callback_function)

# Contract details
details = mds.get_contract_details(contract)
```

### Quote Object

```python
quote.symbol    # Contract symbol
quote.bid       # Bid price
quote.ask       # Ask price
quote.last      # Last trade price
quote.mid       # Mid price (calculated)
quote.spread    # Bid-ask spread (calculated)
quote.high      # Day high
quote.low       # Day low
quote.volume    # Volume
quote.timestamp # Quote timestamp
```

## Market Data Subscriptions

Note: IBKR requires market data subscriptions for real-time quotes. Without subscriptions, you may receive delayed or limited data. Check your IBKR account for available market data packages.

## License

MIT
