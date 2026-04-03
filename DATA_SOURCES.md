# Data Sources — Financial Analysis Agent

## Purpose
This document lists all data sources the Financial Agent depends on, so the macro_2 extraction pipeline can ensure all needed data is available as local CSVs.

## Critical: API-Only Series (No Local CSV)
These FRED series are used by the agent but have NO local CSV equivalent — they are fetched directly from the FRED API. Adding local CSV extraction for these would improve reliability and reduce API dependency:

| Series ID | Name | Frequency | Used By |
|-----------|------|-----------|---------|
| DCOILBRENTEU | Brent Crude Oil Price | Daily | fred_data.get_oil_fundamentals() |
| WCESTUS1 | US Crude Oil Commercial Stocks | Weekly | fred_data.get_oil_fundamentals() |
| WGTSTUS1 | US Gasoline Stocks | Weekly | fred_data.get_oil_fundamentals() |
| WDISTUS1 | US Distillate Stocks | Weekly | fred_data.get_oil_fundamentals() |
| T10Y2Y | 10Y minus 2Y Treasury Spread | Daily | fred_data.get_yield_curve_data() |
| W270RE1A156NBEA | Nonfarm Business Labor Share | Quarterly | fred_data.get_labor_share_data() |
| AWHMAN | Avg Weekly Hours Manufacturing | Monthly | fred_data.get_manufacturing_hours_data() |
| SLVPRUSD | Silver Price (London Fix) | Daily | fred_data.get_commodity_supply_demand() |
| NGSTUS | US Natural Gas Stocks | Weekly | fred_data.get_commodity_supply_demand() |

## A. Local CSV Files (from /macro_2/historical_data/)

### Market Data (updated daily/weekly)
| CSV File | Content | FRED Series | Frequency |
|----------|---------|-------------|-----------|
| vix_move.csv | VIX + MOVE index | N/A (CBOE/ICE) | Daily |
| dxy.csv | US Dollar Index | N/A | Daily |
| es_futures.csv | S&P 500 E-mini | N/A | Daily |
| rty_futures.csv | Russell 2000 futures | N/A | Daily |
| russell_2000.csv | Russell 2000 index | N/A | Daily |
| gold.csv | Gold futures | N/A | Daily |
| silver.csv | Silver futures | N/A | Daily |
| copper.csv | Copper futures | N/A | Daily |
| crude_oil.csv | WTI crude oil | DCOILWTICO | Daily |
| sp500_ma200.csv | S&P 500 vs 200MA | N/A | Daily |
| shiller_cape.csv | Shiller CAPE ratio | N/A | Monthly |
| cot_gold.csv | COT Gold positioning | N/A | Weekly |
| cot_silver.csv | COT Silver positioning | N/A | Weekly |
| sp500_fundamentals.csv | S&P 500 P/E, P/B | N/A | Monthly |

### FRED Macro Data (with local CSV mapping)
| CSV File | FRED Series | Name | Frequency |
|----------|-------------|------|-----------|
| cpi_headline.csv | CPIAUCSL | CPI All Urban Consumers | Monthly |
| core_cpi.csv | CPILFESL | Core CPI ex food/energy | Monthly |
| pce_headline.csv | PCEPI | PCE Price Index | Monthly |
| core_pce.csv | PCEPILFE | Core PCE ex food/energy | Monthly |
| ppi.csv | PPIFIS | PPI Final Demand | Monthly |
| breakeven_5y.csv | T5YIE | 5Y Inflation Expectations | Daily |
| breakeven_10y.csv | T10YIE | 10Y Inflation Expectations | Daily |
| forward_inflation_5y5y.csv | T5YIFR | 5Y5Y Forward Inflation | Daily |
| unemployment_rate.csv | UNRATE | Unemployment Rate | Monthly |
| nonfarm_payrolls.csv | PAYEMS | Total Nonfarm Payrolls | Monthly |
| initial_claims.csv | ICSA | Initial Jobless Claims | Weekly |
| continuing_claims.csv | CCSA | Continuing Claims | Weekly |
| us_2y_yield.csv | DGS2 | 2Y Treasury Yield | Daily |
| us_5y_yield.csv | DGS5 | 5Y Treasury Yield | Daily |
| 10y_treasury_yield.csv | DGS10 | 10Y Treasury Yield | Daily |
| us_30y_yield.csv | DGS30 | 30Y Treasury Yield | Daily |
| spread_10y3m.csv | T10Y3M | 10Y-3M Spread | Daily |
| fed_funds_effective.csv | FEDFUNDS | Effective Fed Funds Rate | Monthly |
| fed_target_upper.csv | DFEDTARU | Fed Funds Target Upper | Event |
| real_yield_5y.csv | DFII5 | 5Y TIPS Real Yield | Daily |
| real_yield_10y.csv | DFII10 | 10Y TIPS Real Yield | Daily |
| hy_oas.csv | BAMLH0A0HYM2 | HY OAS | Daily |
| ig_oas.csv | BAMLC0A0CM | IG Master OAS | Daily |
| bbb_oas.csv | BAMLC0A4CBBB | BBB OAS | Daily |
| durable_goods_orders.csv | DGORDER | Durable Goods Orders | Monthly |
| manufacturing_employment.csv | MANEMP | Manufacturing Employment | Monthly |
| inventories_sales_ratio.csv | ISRATIO | Inventories/Sales Ratio | Monthly |
| jolts_openings.csv | JTSJOL | JOLTS Job Openings | Monthly |
| jolts_quits_rate.csv | JTSQUR | JOLTS Quits Rate | Monthly |
| jolts_hires.csv | JTSHIL | JOLTS Hires | Monthly |
| jolts_layoffs.csv | JTSLDL | JOLTS Layoffs | Monthly |
| productivity.csv | OPHNFB | Output per Hour | Quarterly |
| unit_labor_costs.csv | ULCNFB | Unit Labor Costs | Quarterly |
| savings_rate.csv | PSAVERT | Personal Savings Rate | Monthly |
| revolving_credit.csv | REVOLSL | Revolving Credit | Monthly |
| delinquency_rate.csv | DRALACBS | All-Loan Delinquency Rate | Quarterly |
| bank_lending_standards.csv | DRTSCILM | Bank Lending Standards | Quarterly |
| housing_starts.csv | HOUST | Housing Starts | Monthly |
| building_permits.csv | PERMIT | Building Permits | Monthly |
| existing_home_sales.csv | EXHOSLUSM495S | Existing Home Sales | Monthly |
| mortgage_rate_30y.csv | MORTGAGE30US | 30Y Mortgage Rate | Weekly |
| median_home_price.csv | MSPUS | Median Home Price | Monthly |
| case_shiller_index.csv | CSUSHPISA | Case-Shiller Home Price | Monthly |
| nfci.csv | NFCI | National Financial Conditions | Weekly |
| sahm_rule.csv | SAHMREALTIME | Sahm Rule Indicator | Monthly |
| consumer_sentiment.csv | UMCSENT | UMich Consumer Sentiment | Monthly |
| us_gdp.csv | GDP | Gross Domestic Product | Quarterly |
| gasoline_price.csv | GASREGW | Regular Gasoline Price | Weekly |
| natural_gas_fred.csv | DHHNGSP | Henry Hub Natural Gas | Daily |
| copper_price_fred.csv | PCOPPUSDM | Global Copper Price | Monthly |
| gold_price_fred.csv | GOLDAMGBD228NLBM | Gold Fixing Price | Daily |

## B. yfinance (On-Demand, Not Pre-Downloaded)

These are fetched live by the agent with 30-min in-memory cache. No local CSV needed.

| Ticker | Purpose | Used By |
|--------|---------|---------|
| XLE | Energy Select Sector SPDR ETF | fred_data._fetch_etf_prices() — energy sector analysis |
| XOP | Oil & Gas Exploration & Production ETF | fred_data._fetch_etf_prices() — oil spike classification |
| KBE | SPDR S&P Bank ETF | fred_data._fetch_etf_prices() — bank equity vs credit stress |
| Any stock/ETF ticker | Murphy TA, Graham analysis | murphy_ta._load_stock_data(), graham_analysis._get_current_price() |

## C. BTC Binance Futures Data (from /btc-enhanced-streak-mitigation/)

Pre-downloaded by sibling project. The agent reads these directly.

| File | Content | Frequency | Rows |
|------|---------|-----------|------|
| price.csv | 5-min OHLCV candles | 5 min | ~12.5K |
| funding_rate.csv | 8-hour funding rates | 8 hours | ~2.8K |
| open_interest.csv | 5-min OI snapshots | 5 min | ~83K |
| global_ls_ratio.csv | Global long/short ratio | 5 min | ~386K |
| top_trader_account_ratio.csv | Top trader account L/S | 5 min | ~446K |
| top_trader_position_ratio.csv | Top trader position L/S | 5 min | ~446K |

## D. External APIs (Live, Not Cached)

| API | Provider | Auth | Purpose |
|-----|----------|------|---------|
| FRED REST API | St. Louis Fed | FRED_API_KEY | Fallback for all 56 FRED series when local CSV is missing |
| Twitter/X API | TwitterAPI.io | TWITTERAPI_IO_KEY | Sentiment search (human-in-the-loop) |
| DuckDuckGo Search | DuckDuckGo | None | Web + news search for verification |

## E. Equity Financials (from /macro_2/historical_data/equity_financials/)

| Directory | Source | Tickers | Columns | Frequency |
|-----------|--------|---------|---------|-----------|
| sec_edgar/ | SEC EDGAR filings | ~503 | 53 | Quarterly |
| yahoo_finance/ | Yahoo Finance API | ~504 | 53 | Quarterly |
| _valuation_snapshot.csv | Market multiples | 20 | ~10 | Point-in-time |

## Update Frequency Summary

| Source | Frequency | Freshness Target |
|--------|-----------|------------------|
| Daily market CSVs (VIX, DXY, yields, etc.) | Daily | Same day |
| Weekly CSVs (claims, mortgage rates, NFCI) | Weekly | Same week |
| Monthly CSVs (CPI, NFP, JOLTS, housing) | Monthly | Within 2 days of release |
| Quarterly CSVs (GDP, productivity, bank lending) | Quarterly | Within 2 days of release |
| BTC data | Continuous (5-min) | <1 hour old |
| Equity financials | Quarterly | Within 1 week of earnings |
| IBKR news headlines (7 providers) | On-demand / 3x daily | <12 hours old |
| ES sentiment analysis (NLP + newsletters) | 3x daily (11am/8pm/11pm) | <12 hours old |
| Gmail newsletters (9 sources) | On-demand via /digest_ES | <24 hours old |
