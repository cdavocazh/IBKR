#!/usr/bin/env python3
"""
Standalone Mean-Reversion Scalper Backtest for High-Vol ES Days.

Completely separate from the composite strategy. Tests pure intraday
mean-reversion signals on 5-min bars during high-volatility periods.

Signals tested:
1. RSI extreme bounce (RSI < threshold on short period)
2. Bollinger Band penetration (price below lower band)
3. VWAP reversion (price > N% below VWAP)
4. Volume climax (volume spike + price reversal)
5. Distance from open (price dropped > N% from daily open)
6. Combined: multiple signals confirming = higher conviction

Usage:
    python scripts/backtest_mr_scalper.py
    python scripts/backtest_mr_scalper.py --signal rsi --rsi-entry 20 --hold 12
"""
import argparse
import json
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

import os as _os
PROJECT_ROOT = Path(__file__).parent.parent
# Default to ~/Github/macro_2; override via MACRO_DATA_DIR env var.
MACRO_PATH = Path(_os.environ.get(
    "MACRO_DATA_DIR",
    str(Path.home() / "Github" / "macro_2" / "historical_data"),
))


@dataclass
class ScalperConfig:
    # Which days to trade
    min_daily_atr_pct: float = 1.5   # Only trade on high-vol days
    max_daily_atr_pct: float = 5.0   # Skip extreme crash days

    # Entry signals (any combination)
    use_rsi: bool = True
    rsi_period: int = 12
    rsi_long_entry: float = 20       # RSI below this = buy
    rsi_short_entry: float = 80      # RSI above this = sell

    use_bb: bool = True
    bb_period: int = 20
    bb_std: float = 2.0
    bb_long_entry: float = 0.0       # Price below lower band
    bb_short_entry: float = 1.0      # Price above upper band

    use_vwap: bool = True
    vwap_long_pct: float = -0.5      # Price > 0.5% below VWAP = buy
    vwap_short_pct: float = 0.5      # Price > 0.5% above VWAP = sell

    use_dist_from_open: bool = False
    dist_from_open_pct: float = -1.0 # Price > 1% below open = buy

    use_volume_climax: bool = False
    volume_climax_mult: float = 3.0  # Volume > 3x average = climax

    # How many signals must agree
    min_signals: int = 2             # Need at least 2 signals to enter

    # Allowed side
    side: str = "BOTH"               # "LONG", "SHORT", "BOTH"

    # Exit rules
    rsi_long_exit: float = 55        # Exit long when RSI recovers above this
    rsi_short_exit: float = 45       # Exit short when RSI drops below this
    max_hold_bars: int = 24          # Max hold = 2 hours
    stop_atr_mult: float = 1.5      # Stop at 1.5x ATR
    tp_atr_mult: float = 2.0        # TP at 2x ATR (default; can also use RSI exit)

    # Position sizing
    capital: float = 100_000
    risk_per_trade: float = 2_000    # $2K risk per trade
    max_trades_per_day: int = 3
    cooldown_bars: int = 6           # 30 minutes between trades

    # Entry hours (UTC)
    entry_utc_start: int = 14        # 9 AM ET
    entry_utc_end: int = 20          # 3 PM ET (avoid close)


def compute_rsi(closes, period):
    if len(closes) < period + 1:
        return None
    changes = [closes[i] - closes[i-1] for i in range(len(closes) - period, len(closes))]
    gains = [c if c > 0 else 0 for c in changes]
    losses = [-c if c < 0 else 0 for c in changes]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def compute_atr(highs, lows, closes, period):
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(len(closes) - period, len(closes)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i-1]),
                 abs(lows[i] - closes[i-1]))
        trs.append(tr)
    return sum(trs) / period


def run_scalper_backtest(cfg: ScalperConfig):
    """Run the mean-reversion scalper backtest."""
    # Load data
    df = pd.read_parquet(PROJECT_ROOT / "data" / "es" / "ES_combined_5min.parquet")
    if df.index.tz is not None:
        df.index = df.index.tz_convert("America/Chicago").tz_localize(None)

    # Load daily data for vol classification
    daily = pd.read_parquet(PROJECT_ROOT / "data" / "es" / "ES_daily.parquet")
    daily.index = pd.to_datetime(daily.index)
    daily["atr_pct"] = (daily["high"] - daily["low"]) / daily["close"] * 100

    highvol_dates = set(
        daily[(daily["atr_pct"] >= cfg.min_daily_atr_pct) &
              (daily["atr_pct"] <= cfg.max_daily_atr_pct)].index.date
    )

    # Buffers
    closes = []
    highs = []
    lows = []
    volumes = []
    buf_size = max(cfg.bb_period, cfg.rsi_period, 50) + 10

    # VWAP state (resets daily)
    vwap_num = 0.0
    vwap_den = 0.0
    current_date = None
    daily_open = None

    # Trade state
    trades = []
    position = None  # None or {"side", "entry_price", "stop", "tp", "entry_bar", "entry_time"}
    bars_since_trade = cfg.cooldown_bars + 1
    trades_today = 0
    trades_today_date = None
    equity = cfg.capital
    peak_equity = cfg.capital
    max_dd_pct = 0.0
    equity_curve = []

    for idx, (timestamp, row) in enumerate(df.iterrows()):
        bar_date = timestamp.date()
        price = row["close"]
        high = row["high"]
        low = row["low"]
        vol = row["volume"]

        closes.append(price)
        highs.append(high)
        lows.append(low)
        volumes.append(vol)
        if len(closes) > buf_size:
            closes.pop(0)
            highs.pop(0)
            lows.pop(0)
            volumes.pop(0)

        bars_since_trade += 1

        # Reset daily state
        if bar_date != current_date:
            current_date = bar_date
            daily_open = row["open"]
            vwap_num = 0.0
            vwap_den = 0.0

        # Update VWAP
        typical_price = (high + low + price) / 3
        vwap_num += typical_price * vol
        vwap_den += vol
        vwap = vwap_num / vwap_den if vwap_den > 0 else price

        # Track equity
        if position is not None:
            if position["side"] == "LONG":
                unrealized = (price - position["entry_price"]) * 50
            else:
                unrealized = (position["entry_price"] - price) * 50
            current_equity = equity + unrealized
        else:
            current_equity = equity
        peak_equity = max(peak_equity, current_equity)
        if peak_equity > 0:
            dd = (peak_equity - current_equity) / peak_equity * 100
            max_dd_pct = max(max_dd_pct, dd)
        equity_curve.append((timestamp, current_equity))

        # ── Manage existing position ──
        if position is not None:
            bars_held = idx - position["entry_bar"]

            # Stop hit
            if position["side"] == "LONG" and low <= position["stop"]:
                pnl = (position["stop"] - position["entry_price"]) * 50 - 4.50
                equity += pnl
                trades.append({**position, "exit_price": position["stop"],
                              "exit_time": timestamp, "pnl": pnl, "bars_held": bars_held,
                              "exit_reason": "stop"})
                position = None
                bars_since_trade = 0
                continue

            if position["side"] == "SHORT" and high >= position["stop"]:
                pnl = (position["entry_price"] - position["stop"]) * 50 - 4.50
                equity += pnl
                trades.append({**position, "exit_price": position["stop"],
                              "exit_time": timestamp, "pnl": pnl, "bars_held": bars_held,
                              "exit_reason": "stop"})
                position = None
                bars_since_trade = 0
                continue

            # TP hit
            if position["side"] == "LONG" and high >= position["tp"]:
                pnl = (position["tp"] - position["entry_price"]) * 50 - 4.50
                equity += pnl
                trades.append({**position, "exit_price": position["tp"],
                              "exit_time": timestamp, "pnl": pnl, "bars_held": bars_held,
                              "exit_reason": "tp"})
                position = None
                bars_since_trade = 0
                continue

            if position["side"] == "SHORT" and low <= position["tp"]:
                pnl = (position["entry_price"] - position["tp"]) * 50 - 4.50
                equity += pnl
                trades.append({**position, "exit_price": position["tp"],
                              "exit_time": timestamp, "pnl": pnl, "bars_held": bars_held,
                              "exit_reason": "tp"})
                position = None
                bars_since_trade = 0
                continue

            # RSI exit
            if cfg.use_rsi and len(closes) >= cfg.rsi_period + 2:
                rsi = compute_rsi(closes, cfg.rsi_period)
                if rsi is not None:
                    if position["side"] == "LONG" and rsi > cfg.rsi_long_exit:
                        pnl = (price - position["entry_price"]) * 50 - 4.50
                        equity += pnl
                        trades.append({**position, "exit_price": price,
                                      "exit_time": timestamp, "pnl": pnl, "bars_held": bars_held,
                                      "exit_reason": "rsi_exit"})
                        position = None
                        bars_since_trade = 0
                        continue
                    if position["side"] == "SHORT" and rsi < cfg.rsi_short_exit:
                        pnl = (position["entry_price"] - price) * 50 - 4.50
                        equity += pnl
                        trades.append({**position, "exit_price": price,
                                      "exit_time": timestamp, "pnl": pnl, "bars_held": bars_held,
                                      "exit_reason": "rsi_exit"})
                        position = None
                        bars_since_trade = 0
                        continue

            # Max hold
            if bars_held >= cfg.max_hold_bars:
                if position["side"] == "LONG":
                    pnl = (price - position["entry_price"]) * 50 - 4.50
                else:
                    pnl = (position["entry_price"] - price) * 50 - 4.50
                equity += pnl
                trades.append({**position, "exit_price": price,
                              "exit_time": timestamp, "pnl": pnl, "bars_held": bars_held,
                              "exit_reason": "max_hold"})
                position = None
                bars_since_trade = 0

            continue  # Don't enter while in position

        # ── Entry logic (only on high-vol days) ──
        if bar_date not in highvol_dates:
            continue

        if bars_since_trade < cfg.cooldown_bars:
            continue

        if trades_today_date != bar_date:
            trades_today_date = bar_date
            trades_today = 0
        if trades_today >= cfg.max_trades_per_day:
            continue

        # Entry hours check
        if hasattr(timestamp, "hour"):
            utc_hour = timestamp.hour + 6  # Chicago to UTC approximate
            if utc_hour < cfg.entry_utc_start or utc_hour >= cfg.entry_utc_end:
                continue

        if len(closes) < buf_size:
            continue

        atr = compute_atr(highs, lows, closes, 14)
        if atr is None or atr < 2.0:
            continue

        # Count signals
        long_signals = 0
        short_signals = 0

        # Signal 1: RSI extreme
        if cfg.use_rsi:
            rsi = compute_rsi(closes, cfg.rsi_period)
            if rsi is not None:
                if rsi < cfg.rsi_long_entry:
                    long_signals += 1
                if rsi > cfg.rsi_short_entry:
                    short_signals += 1

        # Signal 2: Bollinger Band penetration
        if cfg.use_bb and len(closes) >= cfg.bb_period:
            sma = np.mean(closes[-cfg.bb_period:])
            std = np.std(closes[-cfg.bb_period:])
            lower_bb = sma - cfg.bb_std * std
            upper_bb = sma + cfg.bb_std * std
            if price < lower_bb:
                long_signals += 1
            if price > upper_bb:
                short_signals += 1

        # Signal 3: VWAP reversion
        if cfg.use_vwap and vwap > 0:
            vwap_dist_pct = (price - vwap) / vwap * 100
            if vwap_dist_pct < cfg.vwap_long_pct:
                long_signals += 1
            if vwap_dist_pct > cfg.vwap_short_pct:
                short_signals += 1

        # Signal 4: Distance from open
        if cfg.use_dist_from_open and daily_open and daily_open > 0:
            dist_pct = (price - daily_open) / daily_open * 100
            if dist_pct < cfg.dist_from_open_pct:
                long_signals += 1
            if dist_pct > abs(cfg.dist_from_open_pct):
                short_signals += 1

        # Signal 5: Volume climax
        if cfg.use_volume_climax and len(volumes) >= 20:
            avg_vol = np.mean(volumes[-20:])
            if vol > avg_vol * cfg.volume_climax_mult:
                # Volume climax + direction of current bar
                if price < row["open"]:  # Down bar with climax = selling exhaustion
                    long_signals += 1
                elif price > row["open"]:  # Up bar with climax = buying exhaustion
                    short_signals += 1

        # Determine entry
        side = None
        if long_signals >= cfg.min_signals and cfg.side in ("LONG", "BOTH"):
            side = "LONG"
        elif short_signals >= cfg.min_signals and cfg.side in ("SHORT", "BOTH"):
            side = "SHORT"

        if side is None:
            continue

        # Position sizing
        stop_dist = atr * cfg.stop_atr_mult
        risk_per_contract = stop_dist * 50
        contracts = max(1, int(cfg.risk_per_trade / risk_per_contract))

        # Only trade if risk is reasonable
        if risk_per_contract > cfg.capital * 0.05:
            continue

        tp_dist = atr * cfg.tp_atr_mult

        if side == "LONG":
            stop = price - stop_dist
            tp = price + tp_dist
        else:
            stop = price + stop_dist
            tp = price - tp_dist

        position = {
            "side": side,
            "entry_price": price,
            "stop": stop,
            "tp": tp,
            "entry_bar": idx,
            "entry_time": timestamp,
            "contracts": contracts,
        }
        trades_today += 1
        bars_since_trade = 0

    # Close any remaining position
    if position is not None:
        last_price = df.iloc[-1]["close"]
        if position["side"] == "LONG":
            pnl = (last_price - position["entry_price"]) * 50 - 4.50
        else:
            pnl = (position["entry_price"] - last_price) * 50 - 4.50
        equity += pnl
        trades.append({**position, "exit_price": last_price,
                      "exit_time": df.index[-1], "pnl": pnl,
                      "bars_held": len(df) - position["entry_bar"],
                      "exit_reason": "eod"})

    # Results
    trades_df = pd.DataFrame(trades)
    total_trades = len(trades_df)
    if total_trades > 0:
        win_rate = (trades_df["pnl"] > 0).mean() * 100
        total_pnl = trades_df["pnl"].sum()
        avg_pnl = trades_df["pnl"].mean()
        winners = trades_df[trades_df["pnl"] > 0]
        losers = trades_df[trades_df["pnl"] <= 0]
        avg_win = winners["pnl"].mean() if len(winners) > 0 else 0
        avg_loss = losers["pnl"].mean() if len(losers) > 0 else 0
        pf = abs(winners["pnl"].sum() / losers["pnl"].sum()) if len(losers) > 0 and losers["pnl"].sum() != 0 else 10.0
        avg_bars = trades_df["bars_held"].mean()

        # Exit reason breakdown
        exit_reasons = trades_df["exit_reason"].value_counts().to_dict()

        # Long vs short
        longs = trades_df[trades_df["side"] == "LONG"]
        shorts = trades_df[trades_df["side"] == "SHORT"]
    else:
        win_rate = total_pnl = avg_pnl = avg_win = avg_loss = pf = avg_bars = 0
        exit_reasons = {}
        longs = shorts = pd.DataFrame()

    return_pct = (equity / cfg.capital - 1) * 100

    return {
        "total_trades": total_trades,
        "return_pct": round(return_pct, 2),
        "total_pnl": round(total_pnl, 2) if total_trades > 0 else 0,
        "max_dd_pct": round(max_dd_pct, 2),
        "win_rate": round(win_rate, 1),
        "profit_factor": round(pf, 2),
        "avg_pnl": round(avg_pnl, 2) if total_trades > 0 else 0,
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "avg_bars_held": round(avg_bars, 1) if total_trades > 0 else 0,
        "long_trades": len(longs),
        "short_trades": len(shorts),
        "long_pnl": round(longs["pnl"].sum(), 2) if len(longs) > 0 else 0,
        "short_pnl": round(shorts["pnl"].sum(), 2) if len(shorts) > 0 else 0,
        "exit_reasons": exit_reasons,
        "highvol_days": len(highvol_dates),
    }


def main():
    parser = argparse.ArgumentParser(description="Mean-Reversion Scalper Backtest")
    parser.add_argument("--sweep", action="store_true", help="Run parameter sweep")
    args = parser.parse_args()

    if args.sweep:
        run_sweep()
        return

    # Default config
    cfg = ScalperConfig()
    results = run_scalper_backtest(cfg)
    print(json.dumps(results, indent=2, default=str))


def run_sweep():
    """Sweep across different signal combinations and parameters."""
    configs = []

    # 1. RSI only (various periods and thresholds)
    for rsi_p in [8, 12, 16]:
        for rsi_e in [15, 20, 25, 30]:
            configs.append(("RSI_only", ScalperConfig(
                use_rsi=True, rsi_period=rsi_p, rsi_long_entry=rsi_e, rsi_short_entry=100-rsi_e,
                use_bb=False, use_vwap=False, min_signals=1, side="LONG"
            )))

    # 2. BB only
    for bb_std in [1.5, 2.0, 2.5]:
        configs.append(("BB_only", ScalperConfig(
            use_rsi=False, use_bb=True, bb_std=bb_std, use_vwap=False, min_signals=1, side="LONG"
        )))

    # 3. VWAP only
    for vwap_pct in [-0.3, -0.5, -0.8, -1.0]:
        configs.append(("VWAP_only", ScalperConfig(
            use_rsi=False, use_bb=False, use_vwap=True, vwap_long_pct=vwap_pct, min_signals=1, side="LONG"
        )))

    # 4. RSI + BB (2 signals required)
    for rsi_e in [20, 25, 30]:
        configs.append(("RSI+BB", ScalperConfig(
            use_rsi=True, rsi_long_entry=rsi_e, rsi_short_entry=100-rsi_e,
            use_bb=True, use_vwap=False, min_signals=2, side="LONG"
        )))

    # 5. RSI + VWAP (2 signals required)
    for rsi_e in [20, 25, 30]:
        for vwap_pct in [-0.3, -0.5]:
            configs.append(("RSI+VWAP", ScalperConfig(
                use_rsi=True, rsi_long_entry=rsi_e, rsi_short_entry=100-rsi_e,
                use_bb=False, use_vwap=True, vwap_long_pct=vwap_pct, min_signals=2, side="LONG"
            )))

    # 6. All signals (2 or 3 required)
    for min_sig in [2, 3]:
        for rsi_e in [20, 25]:
            configs.append((f"ALL_{min_sig}sig", ScalperConfig(
                use_rsi=True, rsi_long_entry=rsi_e, rsi_short_entry=100-rsi_e,
                use_bb=True, use_vwap=True, use_dist_from_open=True, dist_from_open_pct=-0.5,
                use_volume_climax=True, min_signals=min_sig, side="LONG"
            )))

    # 7. BOTH sides
    for rsi_e in [20, 25]:
        configs.append(("BOTH_RSI+BB", ScalperConfig(
            use_rsi=True, rsi_long_entry=rsi_e, rsi_short_entry=100-rsi_e,
            use_bb=True, use_vwap=False, min_signals=2, side="BOTH"
        )))

    # 8. Different hold periods
    for hold in [6, 12, 24, 48]:
        configs.append((f"RSI20_hold{hold}", ScalperConfig(
            use_rsi=True, rsi_long_entry=20, use_bb=False, use_vwap=False,
            min_signals=1, side="LONG", max_hold_bars=hold
        )))

    # 9. Different stop/TP ratios
    for stop_m in [1.0, 1.5, 2.0]:
        for tp_m in [1.5, 2.0, 3.0]:
            configs.append((f"SL{stop_m}_TP{tp_m}", ScalperConfig(
                use_rsi=True, rsi_long_entry=20, use_bb=True, use_vwap=False,
                min_signals=2, side="LONG", stop_atr_mult=stop_m, tp_atr_mult=tp_m
            )))

    print(f"Running {len(configs)} configurations...")
    print(f"{'Config':<25} {'Trades':>7} {'Return%':>9} {'DD%':>7} {'WR%':>6} {'PF':>6} {'AvgPnL':>8} {'LongPnL':>9} {'ShortPnL':>9} {'AvgBars':>8}")
    print("-" * 110)

    best_score = -999
    best_name = ""
    best_result = None

    for name, cfg in configs:
        r = run_scalper_backtest(cfg)
        score = r["return_pct"] * (1 - r["max_dd_pct"] / 100) if r["max_dd_pct"] < 60 and r["win_rate"] >= 30 else 0
        if score > best_score:
            best_score = score
            best_name = name
            best_result = r

        if r["total_trades"] > 0:
            print(f"{name:<25} {r['total_trades']:>7} {r['return_pct']:>+8.2f}% {r['max_dd_pct']:>6.1f}% {r['win_rate']:>5.1f}% {r['profit_factor']:>5.2f} {r['avg_pnl']:>+7.0f} {r['long_pnl']:>+8.0f} {r['short_pnl']:>+8.0f} {r['avg_bars_held']:>7.1f}")

    print(f"\n{'='*110}")
    print(f"BEST: {best_name} (score={best_score:.2f})")
    if best_result:
        print(json.dumps(best_result, indent=2, default=str))


if __name__ == "__main__":
    main()
