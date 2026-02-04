# ES Futures Data Sources

## IBKR Historical Data (Primary)

Your IBKR subscription provides the best data for ES futures backtesting.

### IBKR Limits

| Timeframe | Max History | Notes |
|-----------|-------------|-------|
| 1-second | 1-2 days | Very limited |
| 1-minute | 1-2 years | Per contract |
| 5-minute | ~5 years | Per contract |
| 1-hour | ~10 years | |
| 1-day | 15+ years | |

### Rate Limits
- 60 historical data requests per 10 minutes
- 6 requests per 2 seconds (pacing)
- The download script handles this automatically

### Data Quality
- Direct exchange data (CME)
- Accurate OHLCV
- Includes volume and bar count
- Contract-specific data (handles rolls)

---

## Alternative ES Data Sources

### 1. CME DataMine (Official)
**Cost:** $$$$ (Expensive)
**URL:** https://www.cmegroup.com/market-data/datamine.html

- Official CME historical data
- Tick-by-tick available
- Goes back decades
- Most accurate source
- Used by institutions

### 2. Databento
**Cost:** $$ (Pay per use)
**URL:** https://databento.com

- Modern API, excellent documentation
- ES futures with full depth
- Tick, second, minute data
- ~$0.01-0.05 per symbol-day
- Good for serious backtesting

```python
# Example (requires subscription)
import databento as db
client = db.Historical("YOUR_API_KEY")
data = client.timeseries.get_range(
    dataset="GLBX.MDP3",
    symbols=["ES.FUT"],
    schema="ohlcv-1m",
    start="2023-01-01",
    end="2024-01-01",
)
```

### 3. Polygon.io
**Cost:** $$ ($199/month for futures)
**URL:** https://polygon.io

- Real-time and historical
- Good API
- 1-minute resolution
- REST and WebSocket

```python
# Example
from polygon import RESTClient
client = RESTClient("YOUR_API_KEY")
bars = client.get_aggs("ES", 1, "minute", "2023-01-01", "2023-12-31")
```

### 4. FirstRate Data
**Cost:** $$ (One-time purchase)
**URL:** https://firstratedata.com

- Downloadable CSV files
- ES 1-minute back to 1997
- ~$50-100 for full history
- Good for one-time purchase
- No API (manual download)

### 5. Kibot
**Cost:** $ (Affordable)
**URL:** https://www.kibot.com

- ES intraday data
- 1-minute back to 2007
- ~$25-50 subscription
- Download as CSV

### 6. QuantConnect / Lean
**Cost:** Free (with platform)
**URL:** https://www.quantconnect.com

- Free futures data in their cloud
- ES data available
- Must use their platform
- Good for research

### 7. Quandl (Nasdaq Data Link)
**Cost:** Free (delayed) / $$ (real-time)
**URL:** https://data.nasdaq.com

- Some free ES data
- CME delayed data available
- API access

---

## Data Quality Comparison

| Source | Quality | History | Cost | API |
|--------|---------|---------|------|-----|
| IBKR | Excellent | 2yr 1min | Free* | Yes |
| CME DataMine | Best | 20+ years | $$$$ | No |
| Databento | Excellent | 5+ years | $$ | Yes |
| Polygon | Very Good | 2+ years | $$ | Yes |
| FirstRate | Good | 25+ years | $ | No |
| Kibot | Good | 15+ years | $ | Yes |

*Free with IBKR account and market data subscription

---

## Recommendations

### For Serious Backtesting
1. **Start with IBKR** (free with your account)
2. **Add FirstRate Data** for longer history ($50 one-time)
3. **Consider Databento** for tick data

### For Research/Learning
1. **IBKR** is sufficient
2. **QuantConnect** for cloud-based research

### For Production Trading
1. **IBKR** real-time + historical
2. **Databento** or **Polygon** for redundancy

---

## Loading External Data

The framework can load data from any source as long as it's in the right format:

```python
import pandas as pd
from backtest.engine import BacktestEngine

# Load your CSV/Parquet with columns: open, high, low, close, volume
# Index should be datetime
df = pd.read_csv("your_es_data.csv", index_col=0, parse_dates=True)

# Ensure column names match
df.columns = ["open", "high", "low", "close", "volume"]

# Run backtest
engine = BacktestEngine(data=df)
```

### Required Columns
- `open` - Opening price
- `high` - High price
- `low` - Low price
- `close` - Closing price
- `volume` - Volume (optional but recommended)

### Index
- Must be `DatetimeIndex`
- Timezone-aware recommended (US/Eastern for ES)
