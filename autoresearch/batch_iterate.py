#!/usr/bin/env python3
"""
Batch parameter sweep for ES autoresearch.

Reads current es_strategy_config.py dynamically, generates single-parameter
variations, and runs autoresearch.py evaluate for each.

Usage:
  python batch_iterate.py 1000          # run 1000 iterations
  python batch_iterate.py 1000 --report-every 50
"""

import argparse
import importlib.util
import random
import re
import subprocess
import sys
import time
from pathlib import Path

AUTORESEARCH_DIR = Path(__file__).parent
CONFIG_FILE = AUTORESEARCH_DIR / "es_strategy_config.py"


def load_current_config():
    """Dynamically load current config values."""
    spec = importlib.util.spec_from_file_location("es_strategy_config", CONFIG_FILE)
    cfg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cfg)
    return cfg


def apply_change(param_name, old_val, new_val):
    """Apply a single parameter change to es_strategy_config.py.

    Uses regex to find and replace the parameter value.
    Returns True on success, False on failure.
    """
    content = CONFIG_FILE.read_text()

    # Handle boolean values
    if isinstance(new_val, bool):
        old_str = str(old_val)
        new_str = str(new_val)
    elif isinstance(new_val, float):
        # Match the parameter line with various float formats
        pattern = rf'^({param_name}\s*=\s*)[\d._]+(\s*#.*)?$'
        replacement = rf'\g<1>{new_val}\2'
        new_content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
        if new_content == content:
            # Try without underscore in number
            pattern = rf'^({param_name}\s*=\s*)\S+(\s*#.*)?$'
            new_content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
        if new_content != content:
            CONFIG_FILE.write_text(new_content)
            return True
        return False
    elif isinstance(new_val, int):
        pattern = rf'^({param_name}\s*=\s*)[\d_]+(\s*#.*)?$'
        replacement = rf'\g<1>{new_val}\2'
        new_content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
        if new_content != content:
            CONFIG_FILE.write_text(new_content)
            return True
        return False

    # Generic replacement for booleans
    pattern = rf'^({param_name}\s*=\s*)\S+(\s*#.*)?$'
    replacement = rf'\g<1>{new_str}\2'
    new_content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    if new_content != content:
        CONFIG_FILE.write_text(new_content)
        return True
    return False


def generate_sweeps():
    """Generate all single-parameter variations from current config."""
    cfg = load_current_config()
    sweeps = []

    def add(name, current, alternatives):
        for alt in alternatives:
            if alt != current:
                sweeps.append((f"{name} {current}->{alt}", name, current, alt))

    # --- Dip/Rip Filter ---
    add("DIP_RIP_FILTER_ENABLED", getattr(cfg, "DIP_RIP_FILTER_ENABLED", True), [True, False])
    add("DIP_BUY_RSI_THRESHOLD", getattr(cfg, "DIP_BUY_RSI_THRESHOLD", 40),
        [30, 35, 40, 45, 50])
    add("RIP_SELL_RSI_THRESHOLD", getattr(cfg, "RIP_SELL_RSI_THRESHOLD", 60),
        [50, 55, 60, 65, 70])

    # --- Global Indicator Periods ---
    add("RSI_PERIOD", cfg.RSI_PERIOD, [7, 10, 12, 14, 18, 21])
    add("RSI_FAST_PERIOD", cfg.RSI_FAST_PERIOD, [3, 5, 7, 10, 12])
    add("ATR_PERIOD", cfg.ATR_PERIOD, [7, 10, 14, 20, 28])
    add("SMA_FAST", cfg.SMA_FAST, [10, 15, 20, 25, 30])
    add("SMA_SLOW", cfg.SMA_SLOW, [30, 40, 50, 60, 80, 100])
    add("BB_PERIOD", cfg.BB_PERIOD, [10, 15, 20, 25, 30])
    add("BB_STD", cfg.BB_STD, [1.5, 1.8, 2.0, 2.2, 2.5, 3.0])
    add("RSI_FAST_OVERSOLD", getattr(cfg, "RSI_FAST_OVERSOLD", 25), [15, 20, 25, 30, 35])
    add("RSI_FAST_OVERBOUGHT", getattr(cfg, "RSI_FAST_OVERBOUGHT", 75), [65, 70, 75, 80, 85])

    # --- WSJ + DJ-N Sentiment Signal ---
    add("SENTIMENT_SIGNAL_WEIGHT", getattr(cfg, "SENTIMENT_SIGNAL_WEIGHT", 0.15),
        [0.0, 0.05, 0.10, 0.15, 0.20, 0.25])
    add("BULL_WEIGHT_SENTIMENT", getattr(cfg, "BULL_WEIGHT_SENTIMENT", 0.15),
        [0.0, 0.05, 0.10, 0.15, 0.20])
    add("BEAR_WEIGHT_SENTIMENT", getattr(cfg, "BEAR_WEIGHT_SENTIMENT", 0.10),
        [0.0, 0.05, 0.10, 0.15, 0.20])
    add("SIDE_WEIGHT_SENTIMENT", getattr(cfg, "SIDE_WEIGHT_SENTIMENT", 0.10),
        [0.0, 0.05, 0.10, 0.15, 0.20])
    add("SENTIMENT_THRESHOLD_BOOST", getattr(cfg, "SENTIMENT_THRESHOLD_BOOST", 0.05),
        [0.0, 0.03, 0.05, 0.08, 0.10])

    # --- Regime Classification Weights ---
    add("REGIME_SMA_CROSS_WEIGHT", getattr(cfg, "REGIME_SMA_CROSS_WEIGHT", 0.5),
        [0.3, 0.4, 0.5, 0.6, 0.7])
    add("REGIME_PRICE_VS_200_WEIGHT", getattr(cfg, "REGIME_PRICE_VS_200_WEIGHT", 0.3),
        [0.1, 0.2, 0.3, 0.4, 0.5])
    add("REGIME_VIX_WEIGHT", getattr(cfg, "REGIME_VIX_WEIGHT", 0.2),
        [0.0, 0.1, 0.2, 0.3, 0.4])
    add("REGIME_NLP_WEIGHT", getattr(cfg, "REGIME_NLP_WEIGHT", 0.10),
        [0.0, 0.05, 0.10, 0.15, 0.20, 0.25])
    add("REGIME_DIGEST_WEIGHT", getattr(cfg, "REGIME_DIGEST_WEIGHT", 0.10),
        [0.0, 0.05, 0.10, 0.15, 0.20])

    # --- NLP & Digest Integration ---
    add("NLP_SENTIMENT_BOOST", getattr(cfg, "NLP_SENTIMENT_BOOST", 0.10),
        [0.0, 0.05, 0.10, 0.15, 0.20, 0.25])
    add("DIGEST_CONTEXT_BOOST", getattr(cfg, "DIGEST_CONTEXT_BOOST", 0.05),
        [0.0, 0.05, 0.10, 0.15, 0.20])

    # --- Volume Signal ---
    add("VOLUME_SIGNAL_WEIGHT", getattr(cfg, "VOLUME_SIGNAL_WEIGHT", 0.10),
        [0.0, 0.05, 0.10, 0.15, 0.20])
    add("VOLUME_AVG_LOOKBACK", getattr(cfg, "VOLUME_AVG_LOOKBACK", 20),
        [10, 15, 20, 30, 50])
    add("VOLUME_SURGE_THRESHOLD", getattr(cfg, "VOLUME_SURGE_THRESHOLD", 1.5),
        [1.2, 1.5, 2.0, 2.5, 3.0])
    add("VOLUME_DRY_THRESHOLD", getattr(cfg, "VOLUME_DRY_THRESHOLD", 0.5),
        [0.3, 0.4, 0.5, 0.6, 0.7])

    # --- Daily Trend Overlay ---
    add("REGIME_DAILY_TREND_WEIGHT", getattr(cfg, "REGIME_DAILY_TREND_WEIGHT", 0.30),
        [0.10, 0.15, 0.20, 0.25, 0.30, 0.40])
    add("DAILY_TREND_BOOST", getattr(cfg, "DAILY_TREND_BOOST", 0.15),
        [0.0, 0.05, 0.10, 0.15, 0.20, 0.25])
    add("DAILY_COUNTER_TREND_PENALTY", getattr(cfg, "DAILY_COUNTER_TREND_PENALTY", 0.10),
        [0.0, 0.05, 0.10, 0.15, 0.20])
    add("DAILY_RSI_WEIGHT", getattr(cfg, "DAILY_RSI_WEIGHT", 0.15),
        [0.0, 0.05, 0.10, 0.15, 0.20, 0.25])
    add("DAILY_RSI_OVERSOLD", getattr(cfg, "DAILY_RSI_OVERSOLD", 35),
        [25, 30, 35, 40, 45])
    add("DAILY_RSI_OVERBOUGHT", getattr(cfg, "DAILY_RSI_OVERBOUGHT", 65),
        [55, 60, 65, 70, 75])
    add("DAILY_ATR_VOL_ADJUST", getattr(cfg, "DAILY_ATR_VOL_ADJUST", 0.05),
        [0.0, 0.03, 0.05, 0.08, 0.10])

    # --- WSJ + DJ-N Sentiment Signal ---
    add("SENTIMENT_SIGNAL_WEIGHT", getattr(cfg, "SENTIMENT_SIGNAL_WEIGHT", 0.15),
        [0.0, 0.05, 0.10, 0.15, 0.20, 0.25])
    add("BULL_WEIGHT_SENTIMENT", getattr(cfg, "BULL_WEIGHT_SENTIMENT", 0.15),
        [0.0, 0.05, 0.10, 0.15, 0.20, 0.25])
    add("BEAR_WEIGHT_SENTIMENT", getattr(cfg, "BEAR_WEIGHT_SENTIMENT", 0.10),
        [0.0, 0.05, 0.10, 0.15, 0.20])
    add("SIDE_WEIGHT_SENTIMENT", getattr(cfg, "SIDE_WEIGHT_SENTIMENT", 0.10),
        [0.0, 0.05, 0.10, 0.15, 0.20])
    add("SENTIMENT_THRESHOLD_BOOST", getattr(cfg, "SENTIMENT_THRESHOLD_BOOST", 0.05),
        [0.0, 0.02, 0.05, 0.08, 0.10])

    # --- Daily Trend Gate ---
    add("DAILY_TREND_GATE", getattr(cfg, "DAILY_TREND_GATE", True), [True, False])

    # --- Sequential Decision Pipeline ---
    add("SEQUENTIAL_DECISION_ENABLED", getattr(cfg, "SEQUENTIAL_DECISION_ENABLED", True), [True, False])
    add("SEQ_MACRO_REJECT_THRESHOLD", getattr(cfg, "SEQ_MACRO_REJECT_THRESHOLD", -0.4),
        [-0.6, -0.5, -0.4, -0.3, -0.2, -0.1])
    add("SEQ_VOLUME_GATE_ENABLED", getattr(cfg, "SEQ_VOLUME_GATE_ENABLED", True), [True, False])
    add("SEQ_VOLUME_MIN_RATIO", getattr(cfg, "SEQ_VOLUME_MIN_RATIO", 0.3),
        [0.1, 0.2, 0.3, 0.5, 0.7])
    add("SEQ_MACRO_ADVERSE_SIZE_SCALE", getattr(cfg, "SEQ_MACRO_ADVERSE_SIZE_SCALE", 0.6),
        [0.3, 0.4, 0.5, 0.6, 0.8, 1.0])
    add("SEQ_MACRO_FAVORABLE_SIZE_SCALE", getattr(cfg, "SEQ_MACRO_FAVORABLE_SIZE_SCALE", 1.2),
        [1.0, 1.2, 1.5, 1.8, 2.0])

    # --- Adaptive Stop-Loss (macro+TA scaled) ---
    add("ADAPTIVE_STOP_LOW_VOL_SCALE", getattr(cfg, "ADAPTIVE_STOP_LOW_VOL_SCALE", 0.8),
        [0.6, 0.7, 0.8, 0.9, 1.0])
    add("ADAPTIVE_STOP_HIGH_VOL_SCALE", getattr(cfg, "ADAPTIVE_STOP_HIGH_VOL_SCALE", 1.3),
        [1.0, 1.1, 1.2, 1.3, 1.5])
    add("ADAPTIVE_STOP_VIX_RISKOFF_SCALE", getattr(cfg, "ADAPTIVE_STOP_VIX_RISKOFF_SCALE", 0.8),
        [0.6, 0.7, 0.8, 0.9, 1.0])
    add("ADAPTIVE_STOP_VIX_PANIC_SCALE", getattr(cfg, "ADAPTIVE_STOP_VIX_PANIC_SCALE", 0.6),
        [0.4, 0.5, 0.6, 0.7, 0.8])
    add("ADAPTIVE_STOP_VIX_LOW_SCALE", getattr(cfg, "ADAPTIVE_STOP_VIX_LOW_SCALE", 0.9),
        [0.7, 0.8, 0.9, 1.0])
    add("ADAPTIVE_STOP_CREDIT_STRESS_SCALE", getattr(cfg, "ADAPTIVE_STOP_CREDIT_STRESS_SCALE", 0.8),
        [0.6, 0.7, 0.8, 0.9, 1.0])
    add("ADAPTIVE_STOP_DXY_STRONG_SCALE", getattr(cfg, "ADAPTIVE_STOP_DXY_STRONG_SCALE", 0.85),
        [0.7, 0.8, 0.85, 0.9, 1.0])

    # --- Adaptive Cooldown ---
    add("ADAPTIVE_COOLDOWN_ENABLED", getattr(cfg, "ADAPTIVE_COOLDOWN_ENABLED", True), [True, False])
    add("STREAK_LOOKBACK", getattr(cfg, "STREAK_LOOKBACK", 5), [3, 5, 7, 10])
    add("COOLDOWN_WIN_STREAK_MULT", getattr(cfg, "COOLDOWN_WIN_STREAK_MULT", 0.5),
        [0.25, 0.5, 0.75, 1.0])
    add("COOLDOWN_LOSS_STREAK_MULT", getattr(cfg, "COOLDOWN_LOSS_STREAK_MULT", 2.0),
        [1.5, 2.0, 3.0, 4.0])

    # --- Breakout Entry Mode ---
    add("BREAKOUT_ENTRY_ENABLED", getattr(cfg, "BREAKOUT_ENTRY_ENABLED", True), [True, False])
    add("BREAKOUT_LOOKBACK", getattr(cfg, "BREAKOUT_LOOKBACK", 48), [24, 36, 48, 72, 96])
    add("BREAKOUT_VOL_MULT", getattr(cfg, "BREAKOUT_VOL_MULT", 2.0), [1.5, 2.0, 2.5, 3.0])

    # --- Adaptive Take-Profit (macro+TA scaled) ---
    add("ADAPTIVE_TP_TREND_ALIGNED_SCALE", getattr(cfg, "ADAPTIVE_TP_TREND_ALIGNED_SCALE", 1.5),
        [1.0, 1.2, 1.5, 1.8, 2.0])
    add("ADAPTIVE_TP_COUNTER_TREND_SCALE", getattr(cfg, "ADAPTIVE_TP_COUNTER_TREND_SCALE", 0.7),
        [0.5, 0.6, 0.7, 0.8, 1.0])
    add("ADAPTIVE_TP_RSI_EXTENDED_SCALE", getattr(cfg, "ADAPTIVE_TP_RSI_EXTENDED_SCALE", 0.8),
        [0.6, 0.7, 0.8, 0.9, 1.0])
    add("ADAPTIVE_TP_RSI_REVERSAL_SCALE", getattr(cfg, "ADAPTIVE_TP_RSI_REVERSAL_SCALE", 1.3),
        [1.0, 1.2, 1.3, 1.5, 2.0])
    add("ADAPTIVE_TP_VIX_HIGH_SCALE", getattr(cfg, "ADAPTIVE_TP_VIX_HIGH_SCALE", 1.5),
        [1.0, 1.2, 1.5, 2.0, 2.5])
    add("ADAPTIVE_TP_VIX_ELEVATED_SCALE", getattr(cfg, "ADAPTIVE_TP_VIX_ELEVATED_SCALE", 1.2),
        [1.0, 1.1, 1.2, 1.3, 1.5])
    add("ADAPTIVE_TP_VOLUME_SURGE_SCALE", getattr(cfg, "ADAPTIVE_TP_VOLUME_SURGE_SCALE", 1.3),
        [1.0, 1.2, 1.3, 1.5, 2.0])

    # --- In-Trade Macro Adjustments ---
    add("INTRADE_VIX_SPIKE_THRESHOLD", getattr(cfg, "INTRADE_VIX_SPIKE_THRESHOLD", 5.0),
        [3.0, 4.0, 5.0, 7.0, 10.0])
    add("INTRADE_VIX_SPIKE_TIGHTEN", getattr(cfg, "INTRADE_VIX_SPIKE_TIGHTEN", 0.5),
        [0.3, 0.4, 0.5, 0.7, 1.0])
    add("INTRADE_CREDIT_STRESS_TIGHTEN", getattr(cfg, "INTRADE_CREDIT_STRESS_TIGHTEN", 0.7),
        [0.5, 0.6, 0.7, 0.8, 1.0])
    add("INTRADE_TRAILING_VIX_TIGHTEN", getattr(cfg, "INTRADE_TRAILING_VIX_TIGHTEN", 0.7),
        [0.5, 0.6, 0.7, 0.8, 1.0])
    add("INTRADE_RSI_EXTREME_TIGHTEN_ATR", getattr(cfg, "INTRADE_RSI_EXTREME_TIGHTEN_ATR", 0.3),
        [0.2, 0.3, 0.5, 0.7, 1.0])

    # --- Confidence Sizing ---
    add("CONFIDENCE_SIZING_ENABLED", getattr(cfg, "CONFIDENCE_SIZING_ENABLED", True), [True, False])
    add("CONFIDENCE_HIGH_THRESHOLD", getattr(cfg, "CONFIDENCE_HIGH_THRESHOLD", 0.60),
        [0.50, 0.55, 0.60, 0.65, 0.70])
    add("CONFIDENCE_HIGH_MULT", getattr(cfg, "CONFIDENCE_HIGH_MULT", 1.5),
        [1.0, 1.2, 1.5, 2.0, 2.5])
    add("CONFIDENCE_LOW_MULT", getattr(cfg, "CONFIDENCE_LOW_MULT", 0.5),
        [0.3, 0.4, 0.5, 0.6, 0.8])

    # --- Adaptive TP ---
    add("ADAPTIVE_TP_ENABLED", getattr(cfg, "ADAPTIVE_TP_ENABLED", True), [True, False])
    add("ADAPTIVE_TP_FLOOR_ATR", getattr(cfg, "ADAPTIVE_TP_FLOOR_ATR", 5.0),
        [3.0, 4.0, 5.0, 6.0, 8.0, 10.0])

    # --- Asymmetric R:R Floor ---
    add("MIN_RR_RATIO", getattr(cfg, "MIN_RR_RATIO", 2.0),
        [1.5, 2.0, 2.5, 3.0, 4.0])

    # --- Daily Loss Circuit Breaker ---
    add("DAILY_LOSS_CIRCUIT_PCT", getattr(cfg, "DAILY_LOSS_CIRCUIT_PCT", -2.0),
        [-1.0, -1.5, -2.0, -2.5, -3.0, -5.0])

    # --- Volatility Regime Position Scaling ---
    add("VOL_REGIME_SCALING_ENABLED", getattr(cfg, "VOL_REGIME_SCALING_ENABLED", True), [True, False])
    add("VOL_EXTREME_THRESHOLD_PCT", getattr(cfg, "VOL_EXTREME_THRESHOLD_PCT", 2.5),
        [2.0, 2.5, 3.0, 3.5])
    add("VOL_EXTREME_SIZE_SCALE", getattr(cfg, "VOL_EXTREME_SIZE_SCALE", 0.5),
        [0.25, 0.3, 0.5, 0.6, 0.75])
    add("VOL_HIGH_THRESHOLD_PCT", getattr(cfg, "VOL_HIGH_THRESHOLD_PCT", 1.8),
        [1.2, 1.5, 1.8, 2.0])
    add("VOL_HIGH_SIZE_SCALE", getattr(cfg, "VOL_HIGH_SIZE_SCALE", 0.75),
        [0.5, 0.6, 0.75, 0.85, 1.0])

    # --- Momentum Exit ---
    add("MOMENTUM_EXIT_ENABLED", getattr(cfg, "MOMENTUM_EXIT_ENABLED", True), [True, False])
    add("MOMENTUM_EXIT_MIN_BARS", getattr(cfg, "MOMENTUM_EXIT_MIN_BARS", 24),
        [6, 12, 24, 36, 48, 72])
    add("MOMENTUM_RSI_EXIT_ENABLED", getattr(cfg, "MOMENTUM_RSI_EXIT_ENABLED", True), [True, False])
    add("MOMENTUM_RSI_EXTREME", getattr(cfg, "MOMENTUM_RSI_EXTREME", 75),
        [65, 70, 75, 80, 85])

    # --- Per-Regime Parameters (BULL, BEAR, SIDE) ---
    for prefix in ["BULL", "BEAR", "SIDE"]:
        add(f"{prefix}_RSI_OVERSOLD", getattr(cfg, f"{prefix}_RSI_OVERSOLD", 30), [20, 25, 30, 35, 40])
        add(f"{prefix}_RSI_OVERBOUGHT", getattr(cfg, f"{prefix}_RSI_OVERBOUGHT", 70), [60, 65, 70, 75, 80])
        add(f"{prefix}_COMPOSITE_THRESHOLD", getattr(cfg, f"{prefix}_COMPOSITE_THRESHOLD", 0.35),
            [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50])
        add(f"{prefix}_STOP_ATR_MULT", getattr(cfg, f"{prefix}_STOP_ATR_MULT", 2.0),
            [1.0, 1.2, 1.5, 1.8, 2.0, 2.2, 2.5, 3.0, 3.5])
        add(f"{prefix}_TP_ATR_MULT", getattr(cfg, f"{prefix}_TP_ATR_MULT", 4.0),
            [2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 7.0, 8.0])
        add(f"{prefix}_TRAILING_START_R", getattr(cfg, f"{prefix}_TRAILING_START_R", 1.0),
            [0.5, 0.8, 1.0, 1.2, 1.5, 2.0, 2.5])
        add(f"{prefix}_TRAILING_ATR_MULT", getattr(cfg, f"{prefix}_TRAILING_ATR_MULT", 1.0),
            [0.3, 0.5, 0.8, 1.0, 1.2, 1.5, 2.0])
        add(f"{prefix}_MAX_HOLD_BARS", getattr(cfg, f"{prefix}_MAX_HOLD_BARS", 288),
            [72, 144, 288, 432, 576, 864, 1152])
        add(f"{prefix}_RISK_MULT", getattr(cfg, f"{prefix}_RISK_MULT", 1.0),
            [0.4, 0.6, 0.8, 1.0, 1.2, 1.5])
        add(f"{prefix}_WEIGHT_RSI", getattr(cfg, f"{prefix}_WEIGHT_RSI", 0.20),
            [0.10, 0.15, 0.20, 0.25, 0.30, 0.35])
        add(f"{prefix}_WEIGHT_TREND", getattr(cfg, f"{prefix}_WEIGHT_TREND", 0.20),
            [0.10, 0.15, 0.20, 0.25, 0.30, 0.35])
        add(f"{prefix}_WEIGHT_MOMENTUM", getattr(cfg, f"{prefix}_WEIGHT_MOMENTUM", 0.15),
            [0.05, 0.10, 0.15, 0.20, 0.25, 0.30])
        add(f"{prefix}_WEIGHT_BB", getattr(cfg, f"{prefix}_WEIGHT_BB", 0.10),
            [0.05, 0.10, 0.15, 0.20, 0.25])
        add(f"{prefix}_WEIGHT_VIX", getattr(cfg, f"{prefix}_WEIGHT_VIX", 0.10),
            [0.05, 0.10, 0.15, 0.20, 0.25])
        add(f"{prefix}_WEIGHT_MACRO", getattr(cfg, f"{prefix}_WEIGHT_MACRO", 0.15),
            [0.05, 0.10, 0.15, 0.20, 0.25, 0.30])

    # --- Hold Periods ---
    add("MIN_HOLD_BARS", getattr(cfg, "MIN_HOLD_BARS", 6), [3, 6, 12, 18, 24])

    # --- Bull Defensive Mode ---
    add("BULL_DEFENSIVE_ENABLED", getattr(cfg, "BULL_DEFENSIVE_ENABLED", True), [True, False])
    add("BULL_DEFENSIVE_RISK_MULT", getattr(cfg, "BULL_DEFENSIVE_RISK_MULT", 0.5),
        [0.3, 0.4, 0.5, 0.6, 0.8, 1.0])
    add("BULL_DEFENSIVE_STOP_ATR", getattr(cfg, "BULL_DEFENSIVE_STOP_ATR", 2.0),
        [1.0, 1.5, 2.0, 2.5, 3.0])
    add("BULL_DEFENSIVE_TP_ATR", getattr(cfg, "BULL_DEFENSIVE_TP_ATR", 3.0),
        [2.0, 2.5, 3.0, 4.0, 5.0])
    add("BULL_DEFENSIVE_THRESHOLD", getattr(cfg, "BULL_DEFENSIVE_THRESHOLD", 0.40),
        [0.30, 0.35, 0.40, 0.45, 0.50])

    # --- US Open Avoidance ---
    add("AVOID_US_OPEN", getattr(cfg, "AVOID_US_OPEN", True), [True, False])
    add("AVOID_US_OPEN_END_H", getattr(cfg, "AVOID_US_OPEN_END_H", 15),
        [15, 16])  # 15:00 UTC = 30min, 16:00 UTC = 90min avoidance

    # --- Entry Filters ---
    add("COOLDOWN_BARS", cfg.COOLDOWN_BARS,
        [6, 12, 18, 24, 36, 48, 72, 96])
    add("MIN_ATR_THRESHOLD", cfg.MIN_ATR_THRESHOLD,
        [0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0])
    add("MIN_VOLUME_THRESHOLD", cfg.MIN_VOLUME_THRESHOLD,
        [10, 25, 50, 100, 200])
    if hasattr(cfg, "ADX_TRENDING_MIN"):
        add("ADX_TRENDING_MIN", cfg.ADX_TRENDING_MIN, [12, 15, 18, 20, 25, 30])

    # --- VIX 7-Tier Framework ---
    add("VIX_TIER_1", getattr(cfg, "VIX_TIER_1", 14.0), [12.0, 14.0, 16.0])
    add("VIX_TIER_2", getattr(cfg, "VIX_TIER_2", 20.0), [18.0, 20.0, 22.0])
    add("VIX_TIER_3", getattr(cfg, "VIX_TIER_3", 25.0), [22.0, 25.0, 28.0])
    add("VIX_TIER_4", getattr(cfg, "VIX_TIER_4", 30.0), [28.0, 30.0, 35.0])
    add("VIX_COMPLACENCY_SHORT_BOOST", getattr(cfg, "VIX_COMPLACENCY_SHORT_BOOST", 0.05),
        [0.0, 0.05, 0.10, 0.15])
    add("VIX_NORMAL_LONG_BOOST", getattr(cfg, "VIX_NORMAL_LONG_BOOST", 0.05),
        [0.0, 0.05, 0.10, 0.15])
    add("VIX_OPPORTUNITY_LONG_BOOST", getattr(cfg, "VIX_OPPORTUNITY_LONG_BOOST", 0.20),
        [0.10, 0.15, 0.20, 0.25, 0.30])
    add("VIX_RISKOFF_SHORT_BOOST", getattr(cfg, "VIX_RISKOFF_SHORT_BOOST", 0.10),
        [0.0, 0.05, 0.10, 0.15, 0.20])

    # --- CTA Proxy ---
    add("CTA_FULL_DEPLOY_PCT", getattr(cfg, "CTA_FULL_DEPLOY_PCT", 5.0),
        [3.0, 5.0, 7.0, 10.0])
    add("CTA_BUY_POTENTIAL_PCT", getattr(cfg, "CTA_BUY_POTENTIAL_PCT", -5.0),
        [-3.0, -5.0, -7.0, -10.0])
    add("CTA_FULL_DEPLOY_SHORT_BOOST", getattr(cfg, "CTA_FULL_DEPLOY_SHORT_BOOST", 0.10),
        [0.0, 0.05, 0.10, 0.15, 0.20])
    add("CTA_BUY_POTENTIAL_LONG_BOOST", getattr(cfg, "CTA_BUY_POTENTIAL_LONG_BOOST", 0.15),
        [0.0, 0.05, 0.10, 0.15, 0.20])

    # --- Credit Conditions ---
    add("HY_OAS_NORMAL", getattr(cfg, "HY_OAS_NORMAL", 350),
        [250, 300, 350, 400])
    add("HY_OAS_ELEVATED", getattr(cfg, "HY_OAS_ELEVATED", 450),
        [350, 400, 450, 500])
    add("CREDIT_TIGHTENING_LONG_BOOST", getattr(cfg, "CREDIT_TIGHTENING_LONG_BOOST", 0.05),
        [0.0, 0.05, 0.10, 0.15])
    add("CREDIT_WIDENING_SHORT_BOOST", getattr(cfg, "CREDIT_WIDENING_SHORT_BOOST", 0.10),
        [0.0, 0.05, 0.10, 0.15, 0.20])

    # --- DXY ---
    add("DXY_STRONG_THRESHOLD", getattr(cfg, "DXY_STRONG_THRESHOLD", 105.0),
        [103.0, 105.0, 107.0, 110.0])
    add("DXY_WEAK_THRESHOLD", getattr(cfg, "DXY_WEAK_THRESHOLD", 100.0),
        [95.0, 98.0, 100.0, 102.0])
    add("DXY_STRONG_SHORT_BOOST", getattr(cfg, "DXY_STRONG_SHORT_BOOST", 0.05),
        [0.0, 0.05, 0.10, 0.15])
    add("DXY_WEAK_LONG_BOOST", getattr(cfg, "DXY_WEAK_LONG_BOOST", 0.05),
        [0.0, 0.05, 0.10, 0.15])

    # --- Copper ---
    add("COPPER_RISING_LONG_BOOST", getattr(cfg, "COPPER_RISING_LONG_BOOST", 0.05),
        [0.0, 0.05, 0.10, 0.15])
    add("COPPER_FALLING_SHORT_BOOST", getattr(cfg, "COPPER_FALLING_SHORT_BOOST", 0.05),
        [0.0, 0.05, 0.10, 0.15])

    # --- Risk-off Stop Tightening ---
    add("RISKOFF_STOP_TIGHTEN_MULT", getattr(cfg, "RISKOFF_STOP_TIGHTEN_MULT", 0.7),
        [0.5, 0.6, 0.7, 0.8, 0.9, 1.0])

    # --- Limit Orders ---
    add("USE_LIMIT_ORDERS", cfg.USE_LIMIT_ORDERS, [True, False])
    add("LIMIT_OFFSET_ATR", cfg.LIMIT_OFFSET_ATR,
        [0.1, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0])

    # --- Pullback Entry ---
    if hasattr(cfg, "PULLBACK_MIN_PCT"):
        add("PULLBACK_MIN_PCT", cfg.PULLBACK_MIN_PCT,
            [0.1, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0])
    if hasattr(cfg, "PULLBACK_LOOKBACK"):
        add("PULLBACK_LOOKBACK", cfg.PULLBACK_LOOKBACK,
            [12, 24, 36, 48, 72, 96])

    # --- Breakeven & Stop Tightening ---
    add("BREAKEVEN_R", cfg.BREAKEVEN_R, [0.5, 0.8, 1.0, 1.2, 1.5, 2.0])
    add("STOP_TIGHTEN_ON_RSI_EXTREME", cfg.STOP_TIGHTEN_ON_RSI_EXTREME, [True, False])
    add("STOP_TIGHTEN_ATR_MULT", cfg.STOP_TIGHTEN_ATR_MULT,
        [0.5, 0.8, 1.0, 1.2, 1.5, 2.0])

    # --- GARCH Volatility Forecast (Phase 1) ---
    add("GARCH_ENABLED", getattr(cfg, "GARCH_ENABLED", True), [True, False])
    add("GARCH_BLEND_WEIGHT", getattr(cfg, "GARCH_BLEND_WEIGHT", 0.7),
        [0.1, 0.2, 0.3, 0.5, 0.7, 0.9])
    add("GARCH_VOL_INCREASE_SCALE", getattr(cfg, "GARCH_VOL_INCREASE_SCALE", 1.2),
        [1.0, 1.1, 1.2, 1.3, 1.4, 1.5])
    add("GARCH_VOL_DECREASE_SCALE", getattr(cfg, "GARCH_VOL_DECREASE_SCALE", 0.85),
        [0.6, 0.7, 0.8, 0.85, 0.9, 1.0])
    add("GARCH_EXTREME_VOL_THRESHOLD", getattr(cfg, "GARCH_EXTREME_VOL_THRESHOLD", 2.5),
        [1.3, 1.5, 1.8, 2.0, 2.5, 3.0])

    # --- Particle Filter Regime (Phase 2) ---
    add("PARTICLE_REGIME_ENABLED", getattr(cfg, "PARTICLE_REGIME_ENABLED", True), [True, False])
    add("REGIME_PARTICLE_WEIGHT", getattr(cfg, "REGIME_PARTICLE_WEIGHT", 0.10),
        [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30])

    # --- CUSUM Entry Filter (Phase 3) ---
    add("CUSUM_ENTRY_ENABLED", getattr(cfg, "CUSUM_ENTRY_ENABLED", False), [True, False])
    add("CUSUM_WINDOW_BARS", getattr(cfg, "CUSUM_WINDOW_BARS", 6),
        [3, 6, 12, 24, 48])

    # --- tsfresh Data-Driven Features ---
    add("TSFRESH_SIGNAL_WEIGHT", getattr(cfg, "TSFRESH_SIGNAL_WEIGHT", 0.0),
        [0.0, 0.05, 0.10, 0.15, 0.20, 0.25])

    return sweeps


def run_evaluate(description):
    """Run autoresearch.py evaluate and return output."""
    result = subprocess.run(
        [sys.executable, str(AUTORESEARCH_DIR / "autoresearch.py"),
         "evaluate", "-d", description],
        capture_output=True, text=True, timeout=700,
        cwd=str(AUTORESEARCH_DIR),
    )
    output = result.stdout.strip()
    return output


def print_progress_report(iteration, total, state_path):
    """Print a progress report."""
    import json
    state_file = AUTORESEARCH_DIR / "autoresearch-state.json"
    if state_file.exists():
        with open(state_file) as f:
            state = json.load(f)
        print(f"\n{'='*60}")
        print(f"  PROGRESS REPORT — Iteration {iteration}/{total}")
        print(f"{'='*60}")
        print(f"  Best Score:  {state.get('best_score', 0):.2f}% return")
        print(f"  Baseline:    {state.get('baseline_score', 0):.2f}%")
        improvement = state.get('best_score', 0) - state.get('baseline_score', 0)
        print(f"  Improvement: {improvement:+.2f}%")
        print(f"  KEEPs:       {state.get('total_keeps', 0)}")
        print(f"  DISCARDs:    {state.get('total_discards', 0)}")
        print(f"  CRASHes:     {state.get('total_crashes', 0)}")
        print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="Batch parameter sweep")
    parser.add_argument("max_iterations", type=int, help="Max iterations to run")
    parser.add_argument("--report-every", type=int, default=50,
                        help="Print report every N iterations")
    parser.add_argument("--max-dry-passes", type=int, default=5,
                        help="Stop after N consecutive passes with 0 KEEPs")
    args = parser.parse_args()

    print(f"Starting batch sweep: {args.max_iterations} iterations")
    print(f"Report every {args.report_every} iterations")

    completed = 0
    consecutive_dry_passes = 0

    while completed < args.max_iterations:
        # Generate fresh sweep from current config
        sweeps = generate_sweeps()
        random.shuffle(sweeps)
        keeps_this_pass = 0

        print(f"\n--- Pass {consecutive_dry_passes + 1}: {len(sweeps)} variations ---")

        for desc, param_name, old_val, new_val in sweeps:
            if completed >= args.max_iterations:
                break

            completed += 1

            # Apply change
            success = apply_change(param_name, old_val, new_val)
            if not success:
                print(f"[{completed}] SKIP: Could not apply {desc}")
                continue

            # Evaluate
            try:
                output = run_evaluate(desc)
                if "KEEP" in output:
                    keeps_this_pass += 1
                    print(f"[{completed}] *** KEEP *** {desc}")
                    print(f"    {output}")
                    # Break inner loop to regenerate sweeps with new baseline
                    break
                else:
                    status = "DISCARD" if "DISCARD" in output else "OTHER"
                    if completed % 10 == 0:
                        print(f"[{completed}] {status}: {desc}")

            except subprocess.TimeoutExpired:
                print(f"[{completed}] TIMEOUT: {desc}")
            except Exception as e:
                print(f"[{completed}] ERROR: {e}")

            # Report every N iterations
            if completed % args.report_every == 0:
                print_progress_report(completed, args.max_iterations, AUTORESEARCH_DIR)

        if keeps_this_pass == 0 and completed < args.max_iterations:
            consecutive_dry_passes += 1
            print(f"\nDry pass #{consecutive_dry_passes} (0 KEEPs in {len(sweeps)} variations)")
            if consecutive_dry_passes >= args.max_dry_passes:
                print(f"\nStopping: {args.max_dry_passes} consecutive dry passes")
                break
        else:
            consecutive_dry_passes = 0

    # Final report
    print_progress_report(completed, args.max_iterations, AUTORESEARCH_DIR)
    print(f"Completed {completed} iterations total.")


if __name__ == "__main__":
    main()
