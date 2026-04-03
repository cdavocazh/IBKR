# ML & Quantitative Tools Evaluation for ES Strategy

> Evaluated: 2026-03-26 | Current best: +10.98% return, 19.64% DD, 46.15% WR, 13 trades
> Strategy: Regime-based ES futures trading with macro overlay, NLP sentiment, adaptive exits

---

## Summary Matrix

| Tool | What It Does | Priority | Difficulty | Expected Impact |
|---|---|---|---|---|
| **vectorbt** | Vectorized backtesting & portfolio optimization | **HIGH** | Easy | 10-50x faster backtests, enable walk-forward validation |
| **ARCH** | GARCH volatility modeling | **HIGH** | Easy | Replace naive ATR with conditional volatility forecasting |
| **TuneTA** | Distance-correlation indicator optimization | **HIGH** | Medium | Replace brute-force autoresearch with statistically-guided search |
| **tsfresh** | Automated time-series feature extraction | **MEDIUM** | Medium | Discover non-obvious features from price/volume/macro data |
| **mlfinlab** | Advances in Financial ML (Lopez de Prado) | **MEDIUM** | Hard | Triple barrier method, meta-labeling for bet sizing |
| **Qlib** | ML alpha signal generation platform | **LOW** | Hard | Full ML pipeline — overkill for current scale |
| **PyBroker** | ML-integrated backtesting | **LOW** | Medium | Alternative to current engine — migration cost high |
| **FinRL** | Deep RL for trading | **LOW** | Hard | Requires massive data, prone to overfitting on ES |

---

## Detailed Evaluations

### 1. vectorbt (github.com/polakowo/vectorbt)

**What it does**: Vectorized backtesting framework using NumPy/Pandas broadcasting for extreme speed. Enables running thousands of parameter combinations in seconds rather than hours.

**Key features for ES trading**:
- Vectorized indicator computation (RSI, SMA, BB, ATR all computed in one NumPy pass)
- Built-in portfolio simulation with position sizing, fees, slippage
- Parameter space exploration via Cartesian product sweeps
- Walk-forward and cross-validation support
- Interactive plots for equity curves, drawdowns, trade analysis

**How it improves the current strategy**:
- **Autoresearch speed**: Current `batch_iterate.py` runs one config at a time (~3 seconds per iteration). vectorbt could test 1000 parameter combinations simultaneously in <10 seconds. This transforms the autoresearch from hill-climbing (local optima) to grid search (global exploration).
- **Walk-forward validation**: The current strategy optimizes on the full dataset (in-sample only). vectorbt enables proper IS/OOS splits to detect overfitting — critical given we have 14 months of data.
- **Indicator optimization**: Instead of manually tuning RSI period (7 vs 14 vs 21), vectorbt can test all periods simultaneously and show which is statistically significant.

**Integration path**: Keep `es_strategy_config.py` parameters but rewrite `verify_strategy.py` as vectorized operations. The regime classification and composite scoring can be expressed as NumPy array operations.

**Priority**: HIGH — directly addresses the core bottleneck (slow iteration speed = stuck in local optima).

---

### 2. ARCH (github.com/bashtage/arch)

**What it does**: Autoregressive Conditional Heteroskedasticity modeling — specifically GARCH, EGARCH, and related volatility models. Forecasts future volatility based on the clustering property of financial returns.

**Key features for ES trading**:
- GARCH(1,1) and EGARCH for asymmetric volatility (crashes are more volatile than rallies)
- Volatility forecasting 1-step and multi-step ahead
- Conditional variance decomposition
- Bootstrap-based confidence intervals for risk metrics

**How it improves the current strategy**:
- **Replace naive ATR**: The current strategy uses ATR (average true range) for stop/TP sizing and volatility regime detection. ATR is backward-looking and equal-weighted. GARCH gives a *forward-looking* volatility forecast that captures volatility clustering — critical for ES during VIX spikes.
- **Adaptive stop-loss precision**: Instead of scaling stops by `ADAPTIVE_STOP_HIGH_VOL_SCALE = 1.3` (a static multiplier), GARCH predicts tomorrow's volatility based on today's shock + historical persistence. Stops sized to GARCH forecast would automatically widen before high-vol periods and tighten before low-vol periods.
- **Regime detection upgrade**: Current regime uses SMA crossover + VIX tier. Adding a GARCH volatility regime (high-variance vs low-variance states) would create a dual-dimension regime: trend (bull/bear/sideways) x volatility (calm/stressed). The strategy could use different parameters for calm-bull vs stressed-bull.
- **VIX relationship**: GARCH on ES returns correlates strongly with VIX. When the model's conditional variance diverges from VIX, it signals mispricing — a potential entry signal.

**Integration path**: Fit GARCH(1,1) on daily ES returns, save conditional variance forecast per day in a CSV (like `daily_sentiment.csv`). Load in `verify_strategy.py` alongside macro data.

**Priority**: HIGH — direct upgrade to a core component (volatility estimation) with well-understood theory.

---

### 3. TuneTA (github.com/jmrichardson/tuneta)

**What it does**: Optimizes technical analysis indicators using distance correlation rather than brute-force parameter sweeps. Measures the statistical dependence between each indicator configuration and future returns.

**Key features for ES trading**:
- Tests 100s of TA indicator configurations automatically
- Ranks by distance correlation with forward returns (not just profitability)
- Prunes redundant indicators (avoids multicollinearity)
- Supports custom indicators and timeframes

**How it improves the current strategy**:
- **Replace autoresearch for indicator selection**: The current approach manually tunes RSI_PERIOD (7), SMA_FAST (10), SMA_SLOW (50), BB_PERIOD (10), etc. TuneTA would statistically evaluate which period/combination has the strongest predictive relationship with ES returns — potentially discovering that RSI(5) or SMA(30) performs better.
- **Reduce parameter count**: The strategy has ~100+ tunable parameters. TuneTA could identify which indicators actually add predictive value and which are noise. Removing noise indicators would improve robustness and WR.
- **Feature engineering**: Beyond standard TA, TuneTA can evaluate compound indicators (e.g., RSI divergence from price, volume-weighted momentum) that the current composite doesn't include.
- **Complement autoresearch**: Use TuneTA to select the best indicator set, then autoresearch to tune regime-specific weights. Two-stage optimization.

**Integration path**: Run TuneTA on the ES 5-min data to rank indicators. Replace low-correlation indicators in `_compute_composite()` with high-correlation ones. Keep autoresearch for weight tuning.

**Priority**: HIGH — directly addresses the "stuck at local optimum" problem by scientifically selecting indicators.

---

### 4. tsfresh (github.com/blue-yonder/tsfresh)

**What it does**: Automatically extracts hundreds of time-series features from raw data and filters them by statistical significance. Produces feature matrices suitable for ML classification/regression.

**Key features for ES trading**:
- 794 feature extractors (autocorrelation, entropy, spectral, distribution properties)
- Automatic statistical significance filtering (Benjamini-Hochberg correction)
- Handles multiple time series simultaneously (price + volume + macro)
- Feature importance ranking for interpretability

**How it improves the current strategy**:
- **Non-obvious features**: The current strategy uses standard TA (RSI, SMA, BB, ATR, momentum). tsfresh would extract hundreds of statistical features from the same data — some may have much stronger predictive power than RSI. Examples: Hurst exponent (trend persistence), sample entropy (complexity), AR model coefficients, wavelet decomposition.
- **Macro feature engineering**: Apply tsfresh to VIX, DXY, HY OAS, copper, yield curve data to extract features that capture regime transitions before they're visible in simple thresholds (e.g., VIX > 28).
- **Volume profile features**: Extract distribution statistics from the volume data (kurtosis, skewness, energy of time series) to create a more sophisticated volume signal than the current "surge threshold" binary gate.
- **Sentiment feature engineering**: Apply tsfresh to the daily_sentiment.csv time series to extract trend/momentum/reversal features from sentiment — capturing "sentiment momentum" (are newsletters becoming more bearish over 5 days?).

**Integration path**: Run tsfresh offline to generate a feature matrix for the backtest period. Select top-10 features by significance. Add as new signal components in `_compute_composite()` alongside existing RSI/SMA/BB.

**Priority**: MEDIUM — high potential upside but requires careful overfitting control with only 14 months of data.

---

### 5. mlfinlab (github.com/hudson-and-thames/mlfinlab)

**What it does**: Implementation of methods from "Advances in Financial Machine Learning" by Marcos Lopez de Prado. Covers labeling, feature engineering, backtesting, and portfolio construction for quantitative finance.

**Key features for ES trading**:
- **Triple barrier method**: Labels trades as {profit, loss, time-expired} based on dynamic barriers — much more realistic than fixed TP/SL evaluation
- **Meta-labeling**: A secondary ML model that predicts whether the primary signal's trade will be profitable — essentially a confidence filter
- **Fractional differentiation**: Makes price series stationary while preserving memory — better for ML features than raw returns
- **CUSUM filter**: Event-driven sampling that triggers entries only when cumulative returns exceed a threshold — similar to the current dip-buy/rip-sell filter but statistically principled
- **Sequential bootstrapping**: Handles overlapping samples for proper cross-validation

**How it improves the current strategy**:
- **Triple barrier for autoresearch scoring**: Replace the current simple return-based scoring with triple barrier labels. This would properly account for the interaction between stop, TP, and time-based exits rather than treating them independently.
- **Meta-labeling for trade selection**: Train a classifier on historical trades to predict which composite signals will actually be profitable. This could dramatically improve WR from 36% by filtering out false signals.
- **CUSUM as entry filter**: Replace the fixed `COOLDOWN_BARS` with CUSUM event sampling. This would naturally adapt entry frequency to market conditions — more entries during trending periods, fewer during chop.
- **Fractional differentiation for features**: Apply frac-diff to ES prices before computing indicators. This preserves the memory (autocorrelation) that RSI and SMA destroy through first-differencing.

**Integration path**: Significant refactoring required. Start with CUSUM filter (replace cooldown) and triple barrier scoring (replace simple return). Meta-labeling requires a separate ML training step.

**Priority**: MEDIUM — transformative potential but high complexity. Start with CUSUM filter as lowest-hanging fruit.

---

### 6. Qlib (github.com/microsoft/qlib)

**What it does**: Microsoft's AI-oriented quantitative investment platform. Provides end-to-end ML pipeline for alpha signal generation, model training, and portfolio optimization.

**Key features for ES trading**:
- Pre-built ML models (LightGBM, XGBoost, transformer-based) for alpha generation
- Factor library with 150+ pre-computed factors
- Workflow management for ML training/inference pipeline
- Backtest and analysis framework

**How it improves the current strategy**:
- **ML regime detection**: Replace the rule-based regime classifier (SMA cross + VIX tier) with a trained model that considers all macro variables simultaneously. An ensemble (LightGBM) could learn non-linear regime boundaries that static rules miss.
- **Alpha signal generation**: Train a model on the 638 daily ES bars + macro data to predict next-day direction. Use the model's probability as a signal weight in the composite.

**Integration path**: Would require restructuring the data pipeline to Qlib's format. Significant effort for marginal gain given the small dataset (14 months, ~280 trading days).

**Priority**: LOW — too heavy for the current dataset size. Risk of massive overfitting with <300 training samples.

---

### 7. PyBroker (github.com/edtechre/pybroker)

**What it does**: Algorithmic trading framework that integrates ML model training directly into the backtesting pipeline. Supports scikit-learn, PyTorch, and custom models.

**Key features for ES trading**:
- Train ML models as part of the backtest (avoids look-ahead bias)
- Walk-forward model retraining with configurable windows
- Built-in position sizing and risk management
- Indicator library compatible with pandas_ta

**How it improves the current strategy**:
- **Walk-forward ML**: Train a model on rolling 6-month windows, test on next month, retrain. This avoids the overfitting problem that plagues static-window optimization.
- **Integrated pipeline**: Instead of separate scripts for sentiment, regime, composite, and autoresearch, PyBroker could unify everything into a single walk-forward pipeline.

**Integration path**: Would require migrating from the current BacktestEngine to PyBroker's engine. High migration cost for modest improvement.

**Priority**: LOW — migration cost outweighs benefits given the mature custom engine already in place.

---

### 8. FinRL-Library (github.com/AI4Finance-LLC/FinRL-Library)

**What it does**: Deep Reinforcement Learning framework for financial trading. Agents learn optimal policies (when to buy/sell/hold) through trial-and-error interaction with market simulations.

**Key features for ES trading**:
- PPO, A2C, DDPG, SAC, TD3 agents for continuous action spaces
- Multi-asset portfolio support
- Custom environment definition with trading fees, slippage
- State space can include any features (TA, macro, sentiment)

**How it improves the current strategy**:
- **Optimal entry/exit timing**: RL could learn when to enter and exit without explicit composite thresholds — potentially discovering entry patterns that rule-based systems miss.
- **Adaptive position sizing**: RL naturally learns to size positions based on the state (volatility, regime, sentiment).

**Concerns for ES trading**:
- **Data scarcity**: RL requires millions of samples to converge. 14 months of 5-min bars (~48K samples) is far too little — the agent would massively overfit.
- **Non-stationary markets**: RL assumes the environment is stationary (or slowly changing). ES during an Iran war has a completely different distribution than during a tech rally. The agent trained on 2025 data would fail in 2026.
- **Reward shaping**: The Sharpe/Calmar rewards used in FinRL don't naturally map to the specific constraints (WR > 30%, DD < 60%, Asia hours only).

**Priority**: LOW — fundamentally unsuitable for the current dataset size and non-stationary market conditions. Would require years of data and careful environment design.

---

## Recommended Implementation Roadmap

### Phase 1: Quick Wins (1-2 weeks)
1. **ARCH (GARCH)** — Fit GARCH on daily returns, export conditional variance to CSV. Replace ATR-based vol scaling with GARCH forecast. Easy integration, immediate improvement to stop-loss sizing.
2. **TuneTA** — Run distance-correlation analysis on all current indicators vs 5-day forward ES returns. Prune low-correlation indicators, replace with high-correlation ones.

### Phase 2: Infrastructure Upgrade (2-4 weeks)
3. **vectorbt** — Rewrite verify_strategy.py as vectorized operations. Enable proper walk-forward validation (train on 10 months, test on 4 months). 10-50x speedup enables global parameter search.

### Phase 3: Advanced ML (1-2 months)
4. **tsfresh** — Feature engineering on price/volume/macro data. Add top-10 features to composite.
5. **mlfinlab CUSUM** — Replace fixed cooldown with CUSUM event sampling.
6. **mlfinlab Meta-labeling** — Train a binary classifier to filter the composite signal's false positives.

### Phase 4: Full ML Pipeline (3+ months)
7. **Qlib/PyBroker** — Only if dataset grows to 3+ years of data. Currently premature.
8. **FinRL** — Only with 5+ years of data and a dedicated RL engineer. Not recommended for current scale.

---

## Key Insight

The current strategy's biggest limitation isn't the signals — it's the **optimization method**. Hill-climbing with single-parameter changes (autoresearch) gets stuck in local optima. The priority tools (vectorbt, TuneTA, ARCH) directly address this by enabling:
- **Faster exploration** (vectorbt: test 1000x more configs)
- **Smarter selection** (TuneTA: statistically-guided indicator choice)
- **Better modeling** (ARCH: forward-looking volatility vs backward-looking ATR)

These three together could unlock the 40% return target by expanding the search space while improving signal quality.
