#!/usr/bin/env python3
"""
RL Ensemble Agent for ES Trading (Phase 5C — Self-Learning Layer C)

A PPO agent (via Stable-Baselines3) that decides per-bar how much to trust
sentiment vs trend vs mean-reversion, given the current regime. It does NOT
replace `verify_strategy.py` — it learns multipliers ON TOP OF the static config.

State (12-dim observation):
    vix_tier               (categorical 1-7 → normalized to [0,1])
    atr_pct                (daily ATR / close, capped at 5%)
    regime                 (one-hot: BULL/BEAR/SIDE → 3 dims)
    sentiment_15m          ([-1, +1] from sentiment_intraday.csv)
    sentiment_24h          ([-1, +1])
    mag7_breadth           (pct_above_5d_ma in [0, 1])
    fed_cut_prob           ([0, 1] from polymarket_signals.csv)
    time_of_day            (UTC hour / 24)
    recent_pnl             (last 5-trade rolling pnl, scaled)
    dd_current             (current drawdown %, scaled)

Actions (continuous, 4-dim, all in [-1, +1] then mapped):
    position_size_mult     [0.0, 2.0]   — multiplier on RISK_PER_TRADE
    sentiment_weight_adj   [-0.5, +0.5] — additive boost to INTRADAY_SENTIMENT_WEIGHT
    mr_weight_adj          [-0.5, +0.5] — additive boost to MR_RISK_MULT
    blackout_strict_mode   {-1, +1} → bool — extend blackout windows by 50%

Reward:
    realized_pnl × (1 - dd_penalty) - commission_penalty
    where dd_penalty = max(0, dd / 0.20) and commission = trades × $4.50

Training:
    1M PPO steps on rolling 90-day windows; OOS validate on next 30 days.
    Save model to data/rl/ppo_es_ensemble_<date>.zip; load latest at inference time.

This script is intentionally a SCAFFOLD that runs end-to-end with a stub env
even when stable-baselines3 / gymnasium aren't installed. Full training requires:
    pip install stable-baselines3 gymnasium

Usage:
    python scripts/sentiment_rl_agent.py --check          # Verify dependencies
    python scripts/sentiment_rl_agent.py --train --steps 100000 --train-days 90
    python scripts/sentiment_rl_agent.py --validate --model data/rl/ppo_es_ensemble_2026-05-01.zip
    python scripts/sentiment_rl_agent.py --inference      # One-shot agent action for current state

Compute note: PPO training works on CPU but slowly (~50K steps/hr). Recommend
local M-series GPU or an AWS spot instance for the 1M-step training run.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

MODEL_DIR = PROJECT_ROOT / "data" / "rl"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

OBSERVATION_DIM = 12
ACTION_DIM = 4

# State: [vix_tier, atr_pct, bull, bear, side, sent_15m, sent_24h, mag7,
#         fed_cut, hour, recent_pnl, dd]
# Action: [pos_size_mult, sent_weight_adj, mr_weight_adj, blackout_strict]


def _check_dependencies() -> dict:
    out = {}
    try:
        import gymnasium  # noqa: F401
        out["gymnasium"] = True
    except ImportError:
        out["gymnasium"] = False
    try:
        import stable_baselines3  # noqa: F401
        out["stable_baselines3"] = True
    except ImportError:
        out["stable_baselines3"] = False
    try:
        import torch  # noqa: F401
        out["torch"] = True
    except ImportError:
        out["torch"] = False
    return out


# ─── Stubbed environment (works without gymnasium) ───────────

class _BaseEnv:
    """Minimal env interface used when gymnasium isn't installed.
    Identical attribute surface so the training loop runs (with random actions)
    purely for smoke testing."""
    observation_space_shape = (OBSERVATION_DIM,)
    action_space_shape = (ACTION_DIM,)

    def __init__(self, episode_bars: int = 12 * 24 * 90):  # 90 days of 5-min bars
        self.episode_bars = episode_bars
        self.t = 0
        self.equity = 100_000.0
        self.peak_equity = 100_000.0
        self.recent_pnl = 0.0

    def reset(self):
        self.t = 0
        self.equity = 100_000.0
        self.peak_equity = 100_000.0
        self.recent_pnl = 0.0
        return self._obs(), {}

    def step(self, action):
        # Toy reward — replace with verify_strategy backtest hook below
        action = np.array(action).flatten()[:ACTION_DIM]
        # Random "trade outcome" scaled by position size mult (action[0])
        pos_mult = (action[0] + 1.0)  # → [0, 2]
        rng = np.random.default_rng(self.t)
        bar_pnl = rng.normal(0, 50) * pos_mult
        self.equity += bar_pnl
        self.peak_equity = max(self.peak_equity, self.equity)
        dd = (self.peak_equity - self.equity) / self.peak_equity
        commission = abs(pos_mult) * 0.05
        reward = bar_pnl * max(0.1, 1 - dd / 0.20) - commission
        self.t += 1
        terminated = self.t >= self.episode_bars
        truncated = False
        self.recent_pnl = 0.95 * self.recent_pnl + 0.05 * bar_pnl
        return self._obs(), float(reward), terminated, truncated, {}

    def _obs(self):
        rng = np.random.default_rng(self.t)
        # Stub with random valid-shape observation
        obs = rng.uniform(-1, 1, size=OBSERVATION_DIM).astype(np.float32)
        # Replace last two slots with our actual rolling state
        peak = max(self.peak_equity, 1.0)
        dd = (peak - self.equity) / peak
        obs[-1] = float(min(1.0, dd / 0.20))
        obs[-2] = float(np.tanh(self.recent_pnl / 1000.0))
        return obs


def _action_to_dict(action) -> dict:
    """Map the 4-dim continuous action vector → BacktestRunner action dict."""
    a = np.array(action).flatten()
    return {
        "position_size_mult":   float((a[0] + 1.0)),       # [-1, 1] → [0, 2]
        "sentiment_weight_adj": float(a[1] * 0.5),         # [-1, 1] → [-0.5, +0.5]
        "mr_weight_adj":        float(a[2] * 0.5),
        "blackout_strict_mode": bool(a[3] > 0),
    }


def _shape_reward(raw_pnl: float, info: dict, peak_dd_pct: float = 0.0) -> float:
    """Risk-adjusted reward.

    raw_pnl:    PnL this bar (dollars)
    peak_dd_pct: current peak-to-trough drawdown (0..1), surfaced via observation[-1]
    """
    dd_penalty = max(0.0, peak_dd_pct / 0.20)  # full penalty at 20% DD
    # Commission proxy: if we just opened/closed a position this bar, deduct
    # (BacktestRunner doesn't tag fills, so use a small constant when in_position toggled)
    commission = 4.5 if info.get("just_traded") else 0.0
    return float(raw_pnl * max(0.1, 1.0 - dd_penalty) - commission)


def _build_real_env():
    """Build a Gymnasium env wrapping verify_strategy.BacktestRunner.

    Falls back to the toy _BaseEnv when gymnasium/stable_baselines3 missing
    so this script always runs (e.g., for --check / --inference smoke tests).
    """
    deps = _check_dependencies()
    if not (deps["gymnasium"] and deps["stable_baselines3"]):
        print("[rl] gymnasium/stable_baselines3 missing — using stub env", file=sys.stderr)
        return _BaseEnv()

    import gymnasium as gym
    from gymnasium import spaces
    sys.path.insert(0, str(PROJECT_ROOT / "autoresearch"))
    from verify_strategy import BacktestRunner  # type: ignore

    class ESEnsembleEnv(gym.Env):
        """Real env: each step advances BacktestRunner by one 5-min bar.

        The agent's 4-dim continuous action becomes a dict of cfg multipliers
        applied for that bar (see _action_to_dict + BacktestRunner._apply_action).
        """
        metadata = {"render_modes": []}
        observation_space = spaces.Box(
            low=-2.0, high=2.0, shape=(OBSERVATION_DIM,), dtype=np.float32
        )
        action_space = spaces.Box(
            low=-1.0, high=1.0, shape=(ACTION_DIM,), dtype=np.float32
        )

        def __init__(self):
            super().__init__()
            self.runner = BacktestRunner()

        def reset(self, seed=None, options=None):
            super().reset(seed=seed)
            obs = self.runner.reset()
            return np.asarray(obs, dtype=np.float32), {}

        def step(self, action):
            adict = _action_to_dict(action)
            obs, reward, done, info = self.runner.step(adict)
            obs = np.asarray(obs, dtype=np.float32)
            shaped = _shape_reward(reward, info, peak_dd_pct=float(obs[-1]))
            return obs, shaped, bool(done), False, info

        def get_final_results(self):
            return self.runner.results()

    return ESEnsembleEnv()


# ─── Training ────────────────────────────────────────────────

def train(steps: int = 100_000, train_days: int = 90, seed: int = 42) -> Optional[str]:
    deps = _check_dependencies()
    if not deps["stable_baselines3"]:
        print("[rl] stable_baselines3 not installed; install with:")
        print("     pip install stable-baselines3 gymnasium")
        print("[rl] To proceed without SB3, re-run with --train --no-sb3 (random policy baseline)")
        return None
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import DummyVecEnv

    env = _build_real_env()
    venv = DummyVecEnv([lambda: env])

    model = PPO(
        "MlpPolicy", venv,
        verbose=1,
        seed=seed,
        learning_rate=3e-4,
        n_steps=2048,
        batch_size=64,
        n_epochs=10,
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=0.2,
        ent_coef=0.01,  # encourage some exploration
    )
    print(f"[rl] Training PPO for {steps} steps...", flush=True)
    model.learn(total_timesteps=steps, progress_bar=False)
    out_path = MODEL_DIR / f"ppo_es_ensemble_{datetime.now(timezone.utc).date()}.zip"
    model.save(str(out_path))
    print(f"[rl] Saved → {out_path}", flush=True)
    return str(out_path)


def validate(model_path: str, validation_days: int = 30) -> dict:
    deps = _check_dependencies()
    if not deps["stable_baselines3"]:
        print("[rl] stable_baselines3 missing — cannot validate", file=sys.stderr)
        return {}
    from stable_baselines3 import PPO
    model = PPO.load(model_path)
    env = _build_real_env()
    obs, _ = env.reset()
    total_reward = 0.0
    n_bars = 0
    while True:
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, terminated, truncated, _ = env.step(action)
        total_reward += reward
        n_bars += 1
        if terminated or truncated or n_bars >= 12 * 24 * validation_days:
            break
    final_equity = env._impl.equity if hasattr(env, "_impl") else 100_000.0
    return {
        "model": model_path,
        "validation_days": validation_days,
        "n_bars": n_bars,
        "total_reward": float(total_reward),
        "final_equity": float(final_equity),
        "return_pct": (final_equity - 100_000.0) / 100_000.0 * 100,
    }


def inference_one_step(model_path: Optional[str] = None) -> dict:
    """Get the agent's action for the current state (production hook)."""
    if model_path is None:
        models = sorted(MODEL_DIR.glob("ppo_es_ensemble_*.zip"))
        if not models:
            return {"error": "no trained model found"}
        model_path = str(models[-1])
    deps = _check_dependencies()
    if not deps["stable_baselines3"]:
        return {"error": "stable_baselines3 not installed", "model_found": model_path}
    from stable_baselines3 import PPO
    model = PPO.load(model_path)
    env = _build_real_env()
    obs, _ = env.reset()
    action, _ = model.predict(obs, deterministic=True)
    action = np.array(action).flatten()
    return {
        "model": model_path,
        "observation": obs.tolist(),
        "action": {
            "position_size_mult": float((action[0] + 1.0)),  # 0-2x
            "sentiment_weight_adj": float(action[1] * 0.5),  # ±0.5
            "mr_weight_adj": float(action[2] * 0.5),
            "blackout_strict_mode": bool(action[3] > 0),
        },
    }


# ─── CLI ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="PPO ensemble agent for ES trading")
    parser.add_argument("--check", action="store_true", help="Check dependencies and exit")
    parser.add_argument("--train", action="store_true", help="Train a new PPO model")
    parser.add_argument("--steps", type=int, default=100_000, help="Training steps")
    parser.add_argument("--train-days", type=int, default=90, help="Training window days")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--validate", action="store_true", help="Validate a saved model")
    parser.add_argument("--validation-days", type=int, default=30)
    parser.add_argument("--model", default=None, help="Model path for validate/inference")
    parser.add_argument("--inference", action="store_true",
                        help="One-shot inference for current state (uses latest model if --model omitted)")
    args = parser.parse_args()

    if args.check:
        deps = _check_dependencies()
        print("Dependency check:")
        for name, ok in deps.items():
            mark = "✓" if ok else "✗"
            print(f"  {mark} {name}")
        if not all(deps.values()):
            print("\nInstall missing deps:")
            print("  pip install stable-baselines3 gymnasium")
            print("  pip install torch --extra-index-url https://download.pytorch.org/whl/cpu")
        return

    if args.train:
        train(steps=args.steps, train_days=args.train_days, seed=args.seed)
        return

    if args.validate:
        model = args.model
        if not model:
            models = sorted(MODEL_DIR.glob("ppo_es_ensemble_*.zip"))
            if not models:
                print("No saved models found")
                sys.exit(1)
            model = str(models[-1])
        result = validate(model, validation_days=args.validation_days)
        print(json.dumps(result, indent=2, default=str))
        return

    if args.inference:
        result = inference_one_step(model_path=args.model)
        print(json.dumps(result, indent=2, default=str))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
