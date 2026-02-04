# ES Futures Backtesting Guide

## Quick Start

### 1. Download Data

```bash
# Download all available ES data from IBKR
python scripts/download_es_data.py --timeframe all

# Or just 1-minute data
python scripts/download_es_data.py --timeframe 1min --years 2
```

### 2. Run a Backtest

```bash
# Run with default MA crossover strategy
python scripts/run_backtest.py --strategy ma_crossover

# With specific timeframe and dates
python scripts/run_backtest.py \
    --strategy rsi \
    --timeframe 5min \
    --start 2023-01-01 \
    --end 2024-01-01
```

### 3. Compare Strategies

```bash
python scripts/compare_strategies.py --timeframe 5min
```

---

## Creating Custom Strategies

### Basic Strategy

```python
from backtest.strategy import Strategy

class MyStrategy(Strategy):
    def __init__(self):
        super().__init__(name="MyStrategy")
        self.prices = []

    def on_bar(self, engine, bar):
        self.prices.append(bar.close)

        # Need at least 20 bars
        if len(self.prices) < 20:
            return

        # Simple logic: buy if price above 20-bar average
        avg = sum(self.prices[-20:]) / 20

        if bar.close > avg and engine.position.is_flat:
            engine.buy(1)
        elif bar.close < avg and engine.position.is_long:
            engine.close_position()
```

### Using Indicators

```python
from backtest.strategy import Strategy, Indicator

class RSIStrategy(Strategy):
    def __init__(self):
        super().__init__(name="RSI_Custom")
        self.prices = []
        self.highs = []
        self.lows = []
        self.closes = []

    def on_bar(self, engine, bar):
        self.prices.append(bar.close)
        self.highs.append(bar.high)
        self.lows.append(bar.low)
        self.closes.append(bar.close)

        if len(self.prices) < 20:
            return

        # Calculate indicators
        rsi = Indicator.rsi(self.prices, 14)
        atr = Indicator.atr(self.highs, self.lows, self.closes, 14)
        sma = Indicator.sma(self.prices, 20)

        if rsi < 30 and bar.close > sma:
            if engine.position.is_flat:
                engine.buy(1)
        elif rsi > 70:
            if engine.position.is_long:
                engine.close_position()
```

### Strategy with Stop Loss

```python
from backtest.strategy import Strategy
from backtest.engine import OrderType

class StopLossStrategy(Strategy):
    def __init__(self, stop_points=10):
        super().__init__(name="WithStopLoss")
        self.stop_points = stop_points
        self.entry_price = None
        self.prices = []

    def on_bar(self, engine, bar):
        self.prices.append(bar.close)

        if len(self.prices) < 20:
            return

        # Check stop loss
        if engine.position.is_long and self.entry_price:
            if bar.low <= self.entry_price - self.stop_points:
                engine.close_position()
                self.entry_price = None
                return

        # Entry logic
        avg = sum(self.prices[-20:]) / 20

        if bar.close > avg and engine.position.is_flat:
            engine.buy(1)
            self.entry_price = bar.close
```

---

## Running Backtests Programmatically

```python
import pandas as pd
from backtest.engine import BacktestEngine
from backtest.strategy import MovingAverageCrossover
from backtest.analytics import PerformanceAnalytics

# Load data
df = pd.read_parquet("data/es/ES_combined_1min.parquet")

# Create engine
engine = BacktestEngine(
    data=df,
    initial_capital=100000,
    commission_per_contract=2.25,
    slippage_ticks=1,
)

# Create and run strategy
strategy = MovingAverageCrossover(fast_period=10, slow_period=30)
results = engine.run(strategy=strategy)

# Analyze results
analytics = PerformanceAnalytics(
    equity_curve=results["equity_curve"],
    trades=results["trades"],
    initial_capital=100000,
)

# Print report
analytics.print_report()

# Get monthly returns table
monthly = analytics.get_monthly_returns_table()
print(monthly)
```

---

## ES Contract Specifications

Understanding ES specs is critical for realistic backtesting:

| Spec | Value |
|------|-------|
| Symbol | ES |
| Exchange | CME |
| Tick Size | 0.25 points |
| Point Value | $50 |
| Tick Value | $12.50 |
| Contract Months | H (Mar), M (Jun), U (Sep), Z (Dec) |
| Trading Hours | Sun 6pm - Fri 5pm ET (23h/day) |
| Margin (approx) | $13,000-15,000 |

### Example P&L Calculation

```
Entry: 4500.00
Exit:  4510.00
Points gained: 10
P&L = 10 points × $50/point = $500 per contract

With 2 contracts: $1,000
Minus commission: $1,000 - (2 × $2.25 × 2) = $991
```

---

## Available Strategies

### 1. Moving Average Crossover
```python
MovingAverageCrossover(fast_period=10, slow_period=30)
```
- Trend following
- Best in trending markets
- Lags price action

### 2. RSI Mean Reversion
```python
RSIMeanReversion(period=14, oversold=30, overbought=70)
```
- Counter-trend
- Best in ranging markets
- Can catch falling knives

### 3. Breakout Strategy
```python
BreakoutStrategy(lookback=20)
```
- Momentum based
- Catches big moves
- Many false breakouts

### 4. Bollinger Bands
```python
BollingerBandStrategy(period=20, std_dev=2.0)
```
- Mean reversion
- Uses volatility
- Good for ranging

### 5. MACD
```python
MACDStrategy(fast=12, slow=26, signal=9)
```
- Trend + momentum
- Widely used
- Multiple confirmations

---

## Timeframe Selection

| Timeframe | Bars/Day | Use Case |
|-----------|----------|----------|
| 1-minute | ~1,410 | Scalping, HFT research |
| 5-minute | ~282 | Day trading |
| 15-minute | ~94 | Swing intraday |
| 1-hour | ~23 | Swing trading |
| Daily | 1 | Position trading |

### Recommendation
- Start with 5-minute or 15-minute for development
- Use 1-minute for final validation
- Daily for longer-term strategies

---

## Performance Metrics Explained

### Returns
- **Total Return**: Overall percentage gain/loss
- **Annualized Return**: Yearly equivalent return

### Risk
- **Max Drawdown**: Largest peak-to-trough decline
- **Volatility**: Annualized standard deviation
- **VaR (95%)**: Expected worst loss 5% of the time

### Risk-Adjusted
- **Sharpe Ratio**: Return per unit of risk (>1 is good, >2 is excellent)
- **Sortino Ratio**: Like Sharpe but only penalizes downside
- **Calmar Ratio**: Return divided by max drawdown

### Trading
- **Win Rate**: Percentage of profitable trades
- **Profit Factor**: Gross profit / Gross loss (>1.5 is good)
- **Average Trade**: Mean P&L per trade

---

## Tips for Better Backtests

1. **Use realistic costs**
   - Commission: $2.25-4.00 per contract
   - Slippage: 1-2 ticks minimum

2. **Account for market conditions**
   - Test across different market regimes
   - Include 2020 volatility, 2022 bear market

3. **Avoid overfitting**
   - Use walk-forward optimization
   - Keep strategy logic simple
   - Test out-of-sample

4. **Consider execution**
   - Limit orders vs market orders
   - Liquidity during off-hours

5. **Risk management**
   - Never risk more than 2% per trade
   - Use position sizing based on volatility
