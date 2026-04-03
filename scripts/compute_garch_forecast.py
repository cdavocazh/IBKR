#!/usr/bin/env python3
"""
Compute GARCH(1,1) volatility forecasts from daily ES data.

Fits an expanding-window GARCH(1,1) model on daily log-returns and produces
a one-day-ahead conditional variance forecast for each trading day.

Output: data/es/garch_daily_forecast.csv
Columns: date, forecast_vol, realized_vol, vol_ratio, garch_alpha, garch_beta

Usage:
    python scripts/compute_garch_forecast.py
    python scripts/compute_garch_forecast.py --min-window 150
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def compute_garch_forecasts(min_window: int = 100) -> pd.DataFrame:
    """Fit rolling GARCH(1,1) on daily ES returns, forecast next-day vol."""
    from arch import arch_model

    # Load daily data
    daily_path = PROJECT_ROOT / "data" / "es" / "ES_daily.parquet"
    if not daily_path.exists():
        print(f"ERROR: {daily_path} not found", file=sys.stderr)
        sys.exit(1)

    df = pd.read_parquet(daily_path).sort_index()
    print(f"Loaded {len(df)} daily bars: {df.index[0]} to {df.index[-1]}")

    # Compute log returns (percentage scale for GARCH stability)
    df["log_return"] = np.log(df["close"] / df["close"].shift(1)) * 100
    df = df.dropna(subset=["log_return"])

    returns = df["log_return"].values
    dates = df.index

    results = []
    # Expanding window: fit on [0:i], forecast i+1
    for i in range(min_window, len(returns) - 1):
        window_returns = returns[:i + 1]

        try:
            # Fit GARCH(1,1) with Student-t distribution (fat tails)
            model = arch_model(
                window_returns,
                vol="Garch",
                p=1, q=1,
                dist="t",
                mean="Constant",
                rescale=False,
            )
            res = model.fit(disp="off", show_warning=False)

            # One-step-ahead forecast
            forecast = res.forecast(horizon=1)
            forecast_var = forecast.variance.iloc[-1, 0]
            forecast_vol = np.sqrt(forecast_var)  # In % terms (annualized would be * sqrt(252))

            # Realized vol: trailing 20-day std of returns
            realized_vol = np.std(window_returns[-20:]) if len(window_returns) >= 20 else np.std(window_returns)

            # Vol ratio: forecast / realized — >1 means GARCH expects vol increase
            vol_ratio = forecast_vol / realized_vol if realized_vol > 0 else 1.0

            # Extract model params
            params = res.params
            alpha = params.get("alpha[1]", 0)
            beta = params.get("beta[1]", 0)

            results.append({
                "date": dates[i + 1],  # Forecast is for next day
                "forecast_vol": round(forecast_vol, 6),
                "realized_vol": round(realized_vol, 6),
                "vol_ratio": round(vol_ratio, 4),
                "garch_alpha": round(alpha, 4),
                "garch_beta": round(beta, 4),
                "persistence": round(alpha + beta, 4),
            })

        except Exception as e:
            # Skip days where GARCH fails to converge
            if i % 100 == 0:
                print(f"  GARCH fit failed at index {i}: {e}", file=sys.stderr)
            continue

        if (i - min_window) % 50 == 0:
            print(f"  Processed {i - min_window + 1}/{len(returns) - min_window - 1} days...")

    forecast_df = pd.DataFrame(results)
    print(f"\nGenerated {len(forecast_df)} GARCH forecasts")

    if len(forecast_df) > 0:
        print(f"  Date range: {forecast_df['date'].iloc[0]} to {forecast_df['date'].iloc[-1]}")
        print(f"  Avg forecast vol: {forecast_df['forecast_vol'].mean():.4f}")
        print(f"  Avg vol_ratio: {forecast_df['vol_ratio'].mean():.4f}")
        print(f"  Avg persistence (alpha+beta): {forecast_df['persistence'].mean():.4f}")

    return forecast_df


def main():
    parser = argparse.ArgumentParser(description="Compute GARCH volatility forecasts")
    parser.add_argument("--min-window", type=int, default=100,
                        help="Minimum history for GARCH fit (default: 100 days)")
    args = parser.parse_args()

    forecast_df = compute_garch_forecasts(min_window=args.min_window)

    if len(forecast_df) == 0:
        print("ERROR: No forecasts generated", file=sys.stderr)
        sys.exit(1)

    out_path = PROJECT_ROOT / "data" / "es" / "garch_daily_forecast.csv"
    forecast_df.to_csv(out_path, index=False)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
