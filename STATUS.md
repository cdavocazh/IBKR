# IBKR Project Status

**Last Updated:** 2026-01-28

## Overview

This repository contains tools for extracting market data from Interactive Brokers (IBKR) TWS API and backtesting trading strategies on futures contracts.

---

## Data Extraction

### Instruments Covered
| Symbol | Name | Front Month | Exchange |
|--------|------|-------------|----------|
| ES | E-mini S&P 500 | ESH6 | CME |
| GC | Gold | GCG6 | COMEX |
| SI | Silver | SIH6 | COMEX |

### Historical Data Downloaded (~16 MB total)

#### ES (E-mini S&P 500)
| Data Type | File | Size | Rows | Date Range |
|-----------|------|------|------|------------|
| 1-min OHLCV | `ES_1min.parquet` | 2.5 MB | 189,042 | 2025-01-31 to 2026-01-27 |
| 5-min OHLCV | `ES_combined_5min.parquet` | 672 KB | 37,716 | 2025-01-31 to 2026-01-27 |
| Historical Volatility | `ES_historical_volatility_daily.parquet` | 20 KB | 227 | 2025-03-03 to 2026-01-26 |
| Implied Volatility | `ES_implied_volatility_daily.parquet` | 24 KB | 365 | 2024-08-23 to 2026-01-28 |
| Bid/Ask/Mid (hourly) | `ES_*_hourly.parquet` | 24 KB each | 691 | 2025-12-14 to 2026-01-28 |

#### GC (Gold)
| Data Type | File | Size | Rows | Date Range |
|-----------|------|------|------|------------|
| 1-min OHLCV | `GC_1min.parquet` | 4.3 MB | 303,366 | 2025-01-24 to 2026-01-27 |
| 5-min OHLCV | `GC_combined_5mins.parquet` | 1.2 MB | 59,313 | 2024-12-19 to 2026-01-27 |
| Historical Volatility | `GC_historical_volatility_daily.parquet` | 20 KB | 246 | 2025-02-03 to 2026-01-26 |
| Implied Volatility | `GC_implied_volatility_daily.parquet` | 24 KB | 364 | 2024-08-23 to 2026-01-27 |
| Bid/Ask/Mid (hourly) | `GC_*_hourly.parquet` | 28 KB each | 693 | 2025-12-14 to 2026-01-28 |

#### SI (Silver)
| Data Type | File | Size | Rows | Date Range |
|-----------|------|------|------|------------|
| 1-min OHLCV | `SI_1min.parquet` | 3.7 MB | 266,928 | 2025-01-21 to 2026-01-27 |
| 5-min OHLCV | `SI_combined_5mins.parquet` | 1.1 MB | 53,956 | 2024-12-19 to 2026-01-27 |
| Historical Volatility | `SI_historical_volatility_daily.parquet` | 20 KB | 227 | 2025-03-03 to 2026-01-26 |
| Implied Volatility | `SI_implied_volatility_daily.parquet` | 20 KB | 242 | 2025-02-11 to 2026-01-27 |
| Bid/Ask/Mid (hourly) | `SI_*_hourly.parquet` | 28 KB each | 693 | 2025-12-14 to 2026-01-28 |

### Real-Time Snapshots (2026-01-28)
| Symbol | Last Price | Bid/Ask | Spread | Volume | Open Interest | IV |
|--------|------------|---------|--------|--------|---------------|-----|
| ES | 7,035.75 | 7,035.50 / 7,035.75 | 0.25 | 56,744 | 1,886,728 | 12.71% |
| GC | 5,251.50 | 5,251.90 / 5,252.40 | 0.50 | 25,925 | 76,948 | 19.10% |
| SI | 114.91 | 114.91 / 114.94 | 0.04 | 37,283 | 100,680 | 100.33% |

---

## Backtest Strategies

### Original Strategies

| Strategy | Trades | Win Rate | Return | Profit Factor | Max DD |
|----------|--------|----------|--------|---------------|--------|
| ES_scalp_momentum | 21 | 66.67% | -0.09% | 0.95 | 0.68% |
| ES_4h | 118 | 38.98% | -0.53% | 0.72 | 1.28% |
| **GC_buy_dip** | **229** | **50.22%** | **+1.48%** | **1.08** | 1.21% |

### Optimized ES Strategies (NEW)

Based on trend regime analysis, new optimized strategies were developed:

| Strategy | Trades | Win Rate | Return | Profit Factor | Max DD | Notes |
|----------|--------|----------|--------|---------------|--------|-------|
| ES_scalp_optimized | 25 | 36.0% | -0.11% | 0.77 | 1.29% | Stricter filters, fewer trades |
| ES_4h_optimized | 168 | 37.5% | -0.58% | 0.79 | 3.64% | Regime confirmation required |
| **ES_trend_follow** | **24** | **41.67%** | **-0.18%** | **1.14** | 3.53% | **Best PF (>1.0)** |

### ES Longer-Term Strategies (1-4 Day Holds)

New strategies based on Kris's trading approach from `ES trading approach.md`:

| Strategy | Trades | Win Rate | Avg P&L | Profit Factor | Max DD | Avg Hold |
|----------|--------|----------|---------|---------------|--------|----------|
| ES_kris_approach (Bullish) | 31 | **54.8%** | **+$472** | **1.49** | 11.13% | 23h (1 day) |
| ES_kris_approach (Neutral) | 41 | 43.9% | -$43 | 0.77 | 13.71% | 21.7h |
| ES_kris_regime (Auto-switch) | 33 | 48.5% | -$4 | 0.94 | 11.13% | 21.3h |

**Key Features:**
- **Time horizon:** 1-4 days (matches your actual trading approach)
- **Stops:** 0.6% (~36 pts) - tight for precision entries
- **Targets:** 2.5R with breakeven move at 1R, trailing 0.8:1
- **Multi-timeframe RSI:** Checks 30min, 4H, and daily RSI before entry
- **Pattern detection:** Double bottoms/tops, failed breakouts
- **Regime awareness:** Uses ES_stance_history.xlsx for regime switching

### Strategy Details

#### 1. ES Kris Approach - Bullish (BEST ES STRATEGY)
- **File:** `backtest/strategies/es_kris_approach.py`
- **Holding Period:** ~23 hours (1 day)
- **Profit Factor:** 1.49 | **Win Rate:** 54.8% | **Avg P&L:** +$472/trade
- **Approach:** Pattern-based entries with tight stops and trailing
- **Key Features (from your trading approach):**
  - 0.6% stops (~36 pts) with 2.5R targets
  - Move to breakeven at 1R, then trail 0.8:1
  - Multi-timeframe RSI (30m, 4H, daily) for confirmation
  - Double bottom/top and failed breakout patterns
  - No buying when 4H RSI overbought (>70)
  - Run with `python es_kris_approach.py bullish`

#### 2. ES Kris Regime (Auto-Switching)
- **File:** `backtest/strategies/es_kris_regime.py`
- **Holding Period:** ~21 hours
- **Approach:** Automatically switches regime based on ES_stance_history.xlsx
- **Regimes:** Bullish (long-only), Bearish (short-only), Neutral (both)

#### 3. ES Trend Follow
- **File:** `backtest/strategies/es_trend_follow.py`
- **Holding Period:** ~110 minutes
- **Profit Factor:** 1.14
- **Approach:** Pure trend following with strict filters

#### 4. GC Buy-the-Dip (Most Profitable Overall)
- **File:** `backtest/strategies/gc_buy_dip.py`
- **Holding Period:** 1-2 hours
- **Approach:** Long-only mean reversion in uptrend
- **Why it works:** Gold has clearer trends than ES

### Regime Analysis Findings

Analysis of 17,961 ES bars revealed:
- **Bull regime:** 44% of time (trend_strength mean: 0.56)
- **Bear regime:** 35.5% of time
- **Neutral regime:** 20.5% of time

Key indicators for regime changes:
- Bull-to-bear: RSI ~57, trend_strength ~2.6 (overbought in uptrend)
- Bear-to-bull: RSI ~43, trend_strength ~-0.97 (oversold in downtrend)

### HTML Reports
Generated reports in `/reports/`:
- `es_scalp_report.html`
- `es_4h_report.html`
- `gc_buy_dip_report.html`

Each report includes: equity curve, drawdown chart, trade log, and performance metrics.

---

## Account Data

### Positions Export
- **File:** `data/positions_all_accounts_20260128_152400.csv`
- **Accounts:** U19671856, U6372508
- **Total Positions:** 92
- **Note:** Real-time prices show `nan` for US stocks due to API market data subscription requirement (Error 10089)

### Account Summary
- **File:** `data/account_summary_20260128_152225.csv`
- **Metrics:** 188 account-level metrics

---

## Project Structure

```
IBKR/
├── ibkr/                          # Core library modules
│   ├── connection.py              # TWS connection management
│   ├── contracts.py               # Contract definitions
│   ├── market_data.py             # Market data requests
│   ├── futures_data.py            # Futures-specific data handling
│   ├── es_data.py                 # ES-specific utilities
│   ├── data_store.py              # Data storage utilities
│   └── yahoo_data.py              # Yahoo Finance fallback
│
├── backtest/                      # Backtesting framework
│   ├── engine.py                  # Core backtest engine
│   ├── strategy.py                # Base strategy class + indicators
│   ├── analytics.py               # Performance analytics
│   ├── regime.py                  # Market regime detection
│   ├── regime_strategies.py       # Regime-based strategies
│   ├── report_generator.py        # HTML report generation
│   └── strategies/                # Strategy implementations
│       ├── es_scalp_momentum.py   # ES scalping strategy
│       ├── es_4h.py               # ES 4-hour swing strategy
│       └── gc_buy_dip.py          # GC buy-the-dip strategy
│
├── scripts/                       # Executable scripts
│   ├── download_futures_data.py   # Download futures OHLCV
│   ├── extract_all_metrics.py     # Extract all data types
│   ├── get_realtime_snapshot.py   # Real-time market snapshot
│   ├── get_account_positions.py   # Export account positions
│   └── get_positions_delayed.py   # Positions with delayed data
│
├── data/                          # Data storage (~16 MB)
│   ├── es/                        # ES futures data
│   ├── gc/                        # GC futures data
│   ├── si/                        # SI futures data
│   ├── all_realtime_snapshots.json
│   ├── extraction_report.txt
│   └── *.csv                      # Account exports
│
├── reports/                       # Generated HTML reports
│   ├── es_scalp_report.html
│   ├── es_4h_report.html
│   └── gc_buy_dip_report.html
│
└── examples/                      # Usage examples
    ├── get_historical_data.py
    ├── stream_prices.py
    └── get_precious_metals.py
```

---

## Data Availability Notes

### AGGTRADES
- IBKR API does not provide an "AGGTRADES" data type
- For aggregated trade data, use `reqHistoricalData` with `TRADES`
- Tick-by-tick data available via `reqHistoricalTicks` (limited history)

### Open Interest Granularity
- **Real-time OI:** Point-in-time daily value (tick 588)
- **Historical OI:** NOT available via IBKR API
- **Alternatives:**
  - CME daily OI reports (free at cmegroup.com)
  - Quandl/Nasdaq Data Link: ~$30-50/month
  - Barchart: ~$25-100/month
  - Build your own database from daily snapshots

### API Market Data Subscription
- Error 10089 indicates API market data subscription is required
- TWS market data subscription ≠ API market data access
- Enable API data sharing in Account Management portal
- Alternative: Use delayed data with `ib.reqMarketDataType(3)`

---

## Running Scripts

### Prerequisites
```bash
pip install ib_insync pandas numpy
```

### Connect to TWS
1. Open TWS or IB Gateway
2. Enable API connections (Edit → Global Configuration → API → Settings)
3. Note the port (7496 for TWS, 4001 for IB Gateway)

### Download Data
```bash
python scripts/download_futures_data.py
python scripts/extract_all_metrics.py
python scripts/get_realtime_snapshot.py
```

### Run Backtests
```bash
python backtest/strategies/es_scalp_momentum.py
python backtest/strategies/es_4h.py
python backtest/strategies/gc_buy_dip.py

# Generate all HTML reports
python backtest/report_generator.py
```

### Export Account Data
```bash
python scripts/get_account_positions.py
python scripts/get_positions_delayed.py  # For delayed data (no subscription needed)
```

---

## Key Findings

1. **ES Kris Approach (Bullish) is the best ES strategy** (PF 1.49, +$472/trade)
   - Based on your actual trading approach with 1-4 day holds
   - 54.8% win rate with tight stops (0.6%) and trailing
   - Multi-timeframe RSI confirmation prevents overtrading
   - Long-only in bullish regime captures the upward drift

2. **GC Buy-the-Dip remains profitable** (+1.48% return, PF 1.08)
   - Gold has clearer trends than ES
   - Long-only approach works well in bull markets

3. **Shorts underperform in the test period** (Jan 2025 - Jan 2026)
   - ES rose 18.8% (5873 → 6980) during this period
   - Short-only strategies lost money (bearish: PF 0.53)
   - Neutral mode dragged down by shorts

4. **Key strategy parameters from your approach:**
   - **Stops:** 0.4-0.8% (30-60 pts) from entry
   - **Targets:** 2-5R (60-150 pts)
   - **Trailing:** Move to BE at 1R, then trail 1:1
   - **Hold time:** 1-4 days
   - **RSI:** Check on ALL timeframes before entry
   - **Avoid:** Buying when 4H RSI overbought

5. **Regime awareness matters**
   - Bullish-only approach outperforms neutral
   - Use ES_stance_history.xlsx for regime tracking
   - Current stance: Neutral (since Jan 9, 2026)

6. **Data Quality**
   - ~66% of 1-minute bars have zero volume (outside RTH)
   - 5-minute data is cleaner and recommended for strategies

7. **Market Data Subscriptions**
   - Error 10089: API market data subscription required separately
   - Delayed data (15-min) is free and sufficient for position monitoring
