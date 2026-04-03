#!/usr/bin/env python3
"""
Particle Filter (SMC) regime classifier for ES futures.

Inspired by quant_simulation_skill_integration.md Section III:
Sequential Monte Carlo with bootstrap particle filter for real-time
Bayesian updating of regime probabilities.

State-space model:
  - Hidden state: regime probability in logit space (3 states: bull/bear/sideways)
  - Observations: SMA crossover, VIX, price vs 200 SMA, momentum

Instead of the strategy's static weighted-average regime classifier, this
produces a probability distribution over regimes updated with each new bar.

Output: data/es/particle_regime_daily.csv
Columns: date, p_bull, p_bear, p_sideways, regime, confidence

Usage:
    python scripts/compute_particle_regime.py
    python scripts/compute_particle_regime.py --n-particles 5000
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import softmax

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class RegimeParticleFilter:
    """Particle filter for 3-state regime classification.

    Hidden state: logit-space weights for [bull, bear, sideways].
    Each particle is a 3-vector in logit space.
    Observation model: likelihood of observing current indicators given regime.
    """

    def __init__(self, n_particles: int = 3000, process_vol: float = 0.1):
        self.N = n_particles
        self.process_vol = process_vol

        # Initialize particles: start near uniform (logit = 0 for all)
        self.particles = np.random.normal(0, 0.3, (n_particles, 3))
        self.weights = np.ones(n_particles) / n_particles

    def _compute_observation_likelihood(self, particle_probs, indicators):
        """Likelihood of observing indicators given regime probabilities.

        indicators: dict with keys:
          sma_cross: float (-1 to 1, negative = bearish crossover)
          price_vs_200: float (-1 to 1)
          vix_signal: float (-1 to 1)
          momentum: float (% change)
          vol_regime: float (0 = low, 1 = high)
        """
        # Expected indicator values per regime
        # Bull: positive SMA cross, price > 200, low VIX, positive momentum
        # Bear: negative SMA cross, price < 200, high VIX, negative momentum
        # Sideways: near-zero everything

        bull_expected = np.array([0.5, 0.5, -0.3, 0.5, -0.3])
        bear_expected = np.array([-0.5, -0.5, 0.5, -0.5, 0.5])
        side_expected = np.array([0.0, 0.0, 0.0, 0.0, 0.0])

        obs = np.array([
            indicators.get("sma_cross", 0),
            indicators.get("price_vs_200", 0),
            indicators.get("vix_signal", 0),
            indicators.get("momentum", 0),
            indicators.get("vol_regime", 0),
        ])

        # Observation noise
        obs_noise = 0.3

        # Log-likelihood for each regime
        ll_bull = -0.5 * np.sum(((obs - bull_expected) / obs_noise) ** 2)
        ll_bear = -0.5 * np.sum(((obs - bear_expected) / obs_noise) ** 2)
        ll_side = -0.5 * np.sum(((obs - side_expected) / obs_noise) ** 2)

        # Weighted log-likelihood using particle's regime probabilities
        ll = (particle_probs[:, 0] * ll_bull +
              particle_probs[:, 1] * ll_bear +
              particle_probs[:, 2] * ll_side)

        return ll

    def update(self, indicators: dict):
        """Update particles with new observation (one time step)."""
        # 1. Propagate: random walk in logit space
        self.particles += np.random.normal(0, self.process_vol, (self.N, 3))

        # Convert to probabilities via softmax
        probs = np.zeros_like(self.particles)
        for i in range(self.N):
            probs[i] = softmax(self.particles[i])

        # 2. Reweight by observation likelihood
        log_ll = self._compute_observation_likelihood(probs, indicators)
        log_weights = np.log(self.weights + 1e-300) + log_ll
        log_weights -= log_weights.max()  # Numerical stability
        self.weights = np.exp(log_weights)
        self.weights /= self.weights.sum()

        # 3. Resample if ESS too low (systematic resampling from Section III)
        ess = 1.0 / np.sum(self.weights ** 2)
        if ess < self.N / 2:
            self._systematic_resample()

    def _systematic_resample(self):
        """Systematic resampling (lower variance than multinomial)."""
        cumsum = np.cumsum(self.weights)
        u = (np.arange(self.N) + np.random.uniform()) / self.N
        indices = np.searchsorted(cumsum, u)
        indices = np.clip(indices, 0, self.N - 1)
        self.particles = self.particles[indices].copy()
        self.weights = np.ones(self.N) / self.N

    def estimate(self):
        """Weighted average regime probabilities."""
        probs = np.zeros((self.N, 3))
        for i in range(self.N):
            probs[i] = softmax(self.particles[i])
        weighted_probs = np.average(probs, axis=0, weights=self.weights)
        return weighted_probs  # [p_bull, p_bear, p_sideways]


def compute_daily_indicators(df: pd.DataFrame) -> list[dict]:
    """Compute indicator observations for each trading day."""
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)

    results = []
    for i in range(200, n):  # Need 200 bars for SMA200
        date = df.index[i]
        d = date.date() if hasattr(date, "date") else date

        # SMA crossover signal
        sma30 = np.mean(closes[i - 30:i])
        sma50 = np.mean(closes[i - 50:i])
        sma200 = np.mean(closes[i - 200:i])

        sma_cross = 0.0
        if sma50 > 0:
            sma_cross = np.clip((sma30 - sma50) / sma50 * 100, -1, 1)

        # Price vs 200 SMA
        price_vs_200 = 0.0
        if sma200 > 0:
            price_vs_200 = np.clip((closes[i] - sma200) / sma200 * 10, -1, 1)

        # Momentum (20-day)
        if i >= 20 and closes[i - 20] > 0:
            momentum = np.clip((closes[i] - closes[i - 20]) / closes[i - 20] * 10, -1, 1)
        else:
            momentum = 0.0

        # Volatility regime (ATR as % of price)
        if i >= 14:
            trs = []
            for j in range(i - 14, i):
                tr = max(highs[j] - lows[j],
                         abs(highs[j] - closes[j - 1]),
                         abs(lows[j] - closes[j - 1]))
                trs.append(tr)
            atr_pct = np.mean(trs) / closes[i] * 100
            vol_regime = np.clip((atr_pct - 1.0) / 1.5, -1, 1)  # >1% = elevated
        else:
            vol_regime = 0.0

        results.append({
            "date": d,
            "sma_cross": sma_cross,
            "price_vs_200": price_vs_200,
            "vix_signal": 0.0,  # Filled from macro data if available
            "momentum": momentum,
            "vol_regime": vol_regime,
        })

    return results


def main():
    parser = argparse.ArgumentParser(description="Particle filter regime classifier")
    parser.add_argument("--n-particles", type=int, default=3000,
                        help="Number of particles (default: 3000)")
    parser.add_argument("--process-vol", type=float, default=0.08,
                        help="Process volatility (default: 0.08)")
    args = parser.parse_args()

    # Load daily ES data
    daily_path = PROJECT_ROOT / "data" / "es" / "ES_daily.parquet"
    if not daily_path.exists():
        print(f"ERROR: {daily_path} not found", file=sys.stderr)
        sys.exit(1)

    df = pd.read_parquet(daily_path).sort_index()
    print(f"Loaded {len(df)} daily bars: {df.index[0]} to {df.index[-1]}")

    # Load VIX for observation model
    macro_path = Path("/Users/kriszhang/Github/macro_2/historical_data")
    vix_data = {}
    vix_path = macro_path / "vix_move.csv"
    if vix_path.exists():
        vix_df = pd.read_csv(vix_path)
        date_col = "date" if "date" in vix_df.columns else vix_df.columns[0]
        vix_df["_date"] = pd.to_datetime(vix_df[date_col], errors="coerce")
        for _, row in vix_df.dropna(subset=["_date"]).iterrows():
            vix_data[row["_date"].date()] = float(row["vix"])

    # Compute daily indicators
    print("Computing daily indicators...")
    indicators_list = compute_daily_indicators(df)

    # Add VIX signal
    import datetime as dt
    for ind in indicators_list:
        d = ind["date"]
        for offset in range(5):
            check = d - dt.timedelta(days=offset)
            if check in vix_data:
                vix = vix_data[check]
                # Normalize: <20 = -1 (bullish), >30 = 1 (bearish)
                ind["vix_signal"] = np.clip((vix - 20) / 10, -1, 1)
                break

    # Run particle filter
    print(f"Running particle filter with {args.n_particles} particles...")
    pf = RegimeParticleFilter(
        n_particles=args.n_particles,
        process_vol=args.process_vol,
    )

    results = []
    for ind in indicators_list:
        pf.update(ind)
        probs = pf.estimate()

        # Determine regime and confidence
        regime_idx = np.argmax(probs)
        regime_map = {0: "BULLISH", 1: "BEARISH", 2: "SIDEWAYS"}
        regime = regime_map[regime_idx]
        confidence = probs[regime_idx]

        results.append({
            "date": ind["date"],
            "p_bull": round(probs[0], 4),
            "p_bear": round(probs[1], 4),
            "p_sideways": round(probs[2], 4),
            "regime": regime,
            "confidence": round(confidence, 4),
        })

    result_df = pd.DataFrame(results)

    # Save
    out_path = PROJECT_ROOT / "data" / "es" / "particle_regime_daily.csv"
    result_df.to_csv(out_path, index=False)
    print(f"\nSaved {len(result_df)} regime estimates to {out_path}")

    # Summary stats
    print(f"\nRegime distribution:")
    for regime in ["BULLISH", "BEARISH", "SIDEWAYS"]:
        count = (result_df["regime"] == regime).sum()
        pct = count / len(result_df) * 100
        avg_conf = result_df[result_df["regime"] == regime]["confidence"].mean()
        print(f"  {regime:10s}: {count:4d} days ({pct:5.1f}%) avg confidence={avg_conf:.3f}")

    print(f"\nAverage probabilities:")
    print(f"  P(bull):     {result_df['p_bull'].mean():.4f}")
    print(f"  P(bear):     {result_df['p_bear'].mean():.4f}")
    print(f"  P(sideways): {result_df['p_sideways'].mean():.4f}")


if __name__ == "__main__":
    main()
