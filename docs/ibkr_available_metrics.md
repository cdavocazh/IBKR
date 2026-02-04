# IBKR API Available Metrics for Futures (ES, GC, SI)

## Overview

This document outlines all available data metrics from the Interactive Brokers (IBKR) API for futures contracts like ES (E-mini S&P 500), GC (Gold), and SI (Silver).

---

## Historical Data (`reqHistoricalData`)

### Data Types (`whatToShow` parameter)

| Data Type | Description | Availability for Futures |
|-----------|-------------|-------------------------|
| `TRADES` | Trade data (OHLCV) - most commonly used | ✅ Available |
| `MIDPOINT` | Midpoint between bid and ask | ✅ Available |
| `BID` | Bid prices | ✅ Available |
| `ASK` | Ask prices | ✅ Available |
| `BID_ASK` | Time-averaged bid-ask data | ✅ Available |
| `HISTORICAL_VOLATILITY` | 30-day historical volatility | ✅ Available |
| `OPTION_IMPLIED_VOLATILITY` | Implied volatility from options | ✅ Available |
| `ADJUSTED_LAST` | Adjusted for splits/dividends | ❌ Equities only |
| `REBATE_RATE` | Short stock rebate rate | ❌ Equities only |
| `FEE_RATE` | Short stock fee rate | ❌ Equities only |
| `YIELD_*` | Bond yields | ❌ Bonds only |

### Bar Sizes Available

**Seconds:**
- 1 secs, 5 secs, 10 secs, 15 secs, 30 secs

**Minutes:**
- 1 min, 2 mins, 3 mins, 5 mins, 10 mins, 15 mins, 20 mins, 30 mins

**Hours:**
- 1 hour, 2 hours, 3 hours, 4 hours, 8 hours

**Days and larger:**
- 1 day, 1 week, 1 month

### Data Limits by Bar Size

| Bar Size | Maximum History |
|----------|-----------------|
| 1 second | ~2,000 bars |
| 1 minute | 1-2 years |
| 5 minutes | 2+ years |
| 1 hour | 5+ years |
| 1 day | 10+ years |

### Fields Returned per Bar

```python
{
    "date": datetime,      # Bar timestamp
    "open": float,         # Opening price
    "high": float,         # High price
    "low": float,          # Low price
    "close": float,        # Closing price
    "volume": int,         # Trading volume
    "average": float,      # Volume-weighted average price (VWAP)
    "barCount": int,       # Number of trades in the bar
}
```

---

## Real-Time Market Data (`reqMktData`)

### Standard Tick Fields

| Field | Description |
|-------|-------------|
| `bid` | Current bid price |
| `bidSize` | Size at bid |
| `ask` | Current ask price |
| `askSize` | Size at ask |
| `last` | Last trade price |
| `lastSize` | Last trade size |
| `volume` | Daily volume |
| `high` | Day high |
| `low` | Day low |
| `open` | Day open |
| `close` | Previous close |
| `halted` | Trading halt status |

### Generic Tick Types (via `genericTickList` parameter)

| Tick ID | Name | Description |
|---------|------|-------------|
| 100 | Option Volume | Call option volume |
| 101 | Option Volume | Put option volume |
| 104 | Historical Volatility | 30-day HV |
| 105 | Avg Option Volume | Average option volume |
| 106 | Option Implied Volatility | Current IV |
| 162 | Index Future Premium | Index future premium |
| 165 | Misc Stats | Miscellaneous stats |
| 221 | Mark Price | Mark price |
| 225 | Auction Info | Auction data |
| 232 | Last Yield | Last yield |
| 233 | Earnings | Earnings data |
| 236 | Shortable Shares | Shares available to short |
| 256 | Inventory | Inventory data |
| 258 | Fundamental Ratios | Fundamental data |
| 291 | Close Implied Volatility | Close IV |
| 293 | Index Future Premium (Real) | Real-time premium |
| 294 | Bond Analytic Data | Bond analytics |
| 295 | Queue Size | Order queue size |
| 411 | Real-time Historical Volatility | RT 30-day HV |
| 456 | Dividends | Dividend info |
| 460 | Reuters Fundamentals | Reuters data |
| 513 | IB Dividends | IB dividend data |
| 588 | Short-term Volume | Short-term volume |
| 595 | EMA | Exponential moving average |

### Futures-Specific Fields

| Field | Description |
|-------|-------------|
| `futuresOpenInterest` | Open interest for futures |
| `histVolatility` | Historical volatility |
| `impliedVolatility` | Implied volatility |

---

## Additional API Endpoints

### 1. Contract Details (`reqContractDetails`)

Returns contract specifications:
```python
{
    "symbol": "ES",
    "localSymbol": "ESH6",
    "exchange": "CME",
    "currency": "USD",
    "multiplier": "50",
    "minTick": 0.25,
    "priceMagnifier": 1,
    "tradingHours": "...",
    "liquidHours": "...",
    "timeZoneId": "US/Central",
    "category": "FUT",
    "subcategory": "Stock Index",
}
```

### 2. Tick-by-Tick Data (`reqHistoricalTicks`)

Ultra-granular tick data:
- Individual trades
- Bid/ask quotes
- Limited history (few days)

### 3. Real-Time Bars (`reqRealTimeBars`)

- 5-second real-time bars
- Live streaming
- OHLCV data per 5-second interval

### 4. Market Depth / Level 2 (`reqMktDepth`)

- Order book data (DOM)
- Multiple price levels
- Bid/ask sizes at each level
- Requires market data subscription

### 5. News Data (`reqHistoricalNews`)

- News headlines
- Provider-specific
- Filterable by date range

### 6. Head Timestamp (`reqHeadTimeStamp`)

- Returns earliest available data date for a contract
- Useful for data planning

### 7. Histogram Data (`reqHistogramData`)

- Price distribution histogram
- Volume at price levels
- Useful for market profile analysis

### 8. Option Parameters (`reqSecDefOptParams`)

- Option chain parameters
- Strike prices
- Expiration dates
- Multipliers

---

## Rate Limits

| Limit Type | Value |
|------------|-------|
| Historical data requests | 60 per 10 minutes |
| Concurrent market data lines | Based on subscription |
| Request pacing | ~10-15 second delay recommended |

---

## Contract Types

### Regular Futures (`Future`)
- Specific expiration month
- `lastTradeDateOrContractMonth`: "202503" for March 2025
- Supports all historical data options

### Continuous Futures (`ContFuture`)
- Automatically rolls between contracts
- **Limitation**: Cannot use `endDateTime` for historical requests
- Must use `endDateTime=""` (empty string) for current data only

---

## Recommended Data Strategy for Backtesting

1. **For 1-minute data**: Use front-month `Future` contracts with chunked requests
2. **For daily data**: Can use `ContFuture` with empty endDateTime
3. **For real-time**: Use `reqMktData` or `reqRealTimeBars`
4. **For tick data**: Use `reqHistoricalTicks` (limited history)

---

## Example Code

### Download 1-minute OHLCV with Volume

```python
from ib_insync import IB, Future

ib = IB()
ib.connect('127.0.0.1', 4001, clientId=1)

contract = Future('ES', '202503', 'CME', 'USD')
ib.qualifyContracts(contract)

bars = ib.reqHistoricalData(
    contract,
    endDateTime='20260128 12:00:00',
    durationStr='7 D',
    barSizeSetting='1 min',
    whatToShow='TRADES',
    useRTH=False,
    formatDate=1,
)

for bar in bars:
    print(f"{bar.date}: O={bar.open} H={bar.high} L={bar.low} C={bar.close} V={bar.volume}")
```

### Get Historical Volatility

```python
bars = ib.reqHistoricalData(
    contract,
    endDateTime='',
    durationStr='30 D',
    barSizeSetting='1 day',
    whatToShow='HISTORICAL_VOLATILITY',
    useRTH=True,
    formatDate=1,
)
```

### Get Real-Time Data with Extended Ticks

```python
ticker = ib.reqMktData(
    contract,
    genericTickList='104,106,162,411',  # HV, IV, premium, RT HV
    snapshot=False
)
ib.sleep(2)
print(f"HV: {ticker.histVolatility}, IV: {ticker.impliedVolatility}")
```
