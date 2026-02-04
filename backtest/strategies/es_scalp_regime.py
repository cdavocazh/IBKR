"""
ES Regime-Adaptive Scalping Strategy

This strategy adapts its behavior based on detected market regime:
- BULL: Long-only with trend pullback entries
- BEAR: Short-only with trend pullback entries
- NEUTRAL: Mean reversion at Bollinger Band extremes

Key improvements from analysis:
1. Uses regime detection to filter trades
2. Adjusts RSI thresholds based on regime
3. Tighter stops in ranging markets
4. Wider targets in trending markets

Holding Period: 15-60 minutes (3-12 bars on 5-min data)
"""

import pandas as pd
import numpy as np
from typing import Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from backtest.strategy import Strategy, Indicator
from backtest.regime_detector import RegimeDetector, Regime


class ESScalpRegimeStrategy(Strategy):
    """ES Scalping Strategy with Regime Adaptation."""

    def __init__(
        self,
        # Regime detection
        regime_ema_period: int = 50,
        regime_confirmation: int = 3,

        # RSI settings
        rsi_period: int = 7,

        # ATR for stops/targets
        atr_period: int = 14,

        # Bollinger Bands for neutral regime
        bb_period: int = 20,
        bb_std: float = 2.0,

        # Position management
        max_hold_bars: int = 12,
        min_volume: int = 100,
    ):
        super().__init__(name="ES_scalp_regime")

        self.regime_detector = RegimeDetector(
            trend_ema_period=regime_ema_period,
            regime_confirmation_bars=regime_confirmation,
        )

        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.max_hold_bars = max_hold_bars
        self.min_volume = min_volume

        # Data storage
        self.highs = []
        self.lows = []
        self.closes = []
        self.volumes = []

        # Trade state
        self.entry_price = None
        self.entry_bar = None
        self.stop_price = None
        self.target_price = None
        self.trailing_stop = None
        self.trade_direction = None
        self.current_atr = None
        self.current_regime = Regime.NEUTRAL

    def _get_regime_params(self) -> dict:
        """Get trading parameters for current regime."""
        return self.regime_detector.get_regime_params(self.current_regime)

    def _check_bull_entry(self, bar, rsi: float, atr: float) -> bool:
        """Check for long entry in bull regime."""
        params = self._get_regime_params()

        # RSI pullback in bull trend
        if rsi < params['entry_rsi_low'] or rsi > params['entry_rsi_high']:
            return False

        # Price above regime EMA (confirmed uptrend)
        if len(self.closes) >= self.regime_detector.trend_ema_period:
            ema = sum(self.closes[-self.regime_detector.trend_ema_period:]) / self.regime_detector.trend_ema_period
            if bar.close < ema:
                return False

        # Volume confirmation
        if len(self.volumes) > 20:
            avg_vol = sum(self.volumes[-21:-1]) / 20
            if self.volumes[-1] < avg_vol * 0.8:
                return False

        return True

    def _check_bear_entry(self, bar, rsi: float, atr: float) -> bool:
        """Check for short entry in bear regime."""
        params = self._get_regime_params()

        # RSI bounce in bear trend
        if rsi < params['entry_rsi_low'] or rsi > params['entry_rsi_high']:
            return False

        # Price below regime EMA (confirmed downtrend)
        if len(self.closes) >= self.regime_detector.trend_ema_period:
            ema = sum(self.closes[-self.regime_detector.trend_ema_period:]) / self.regime_detector.trend_ema_period
            if bar.close > ema:
                return False

        # Volume confirmation
        if len(self.volumes) > 20:
            avg_vol = sum(self.volumes[-21:-1]) / 20
            if self.volumes[-1] < avg_vol * 0.8:
                return False

        return True

    def _check_neutral_entry(self, bar, rsi: float, bb_data: tuple) -> Optional[str]:
        """Check for mean reversion entry in neutral regime."""
        if bb_data is None:
            return None

        middle, upper, lower = bb_data
        params = self._get_regime_params()

        # Long at lower band
        if bar.close <= lower and rsi < 30:
            return 'long'

        # Short at upper band
        if bar.close >= upper and rsi > 70:
            return 'short'

        return None

    def _enter_trade(self, engine, direction: str, price: float):
        """Enter a trade with regime-appropriate parameters."""
        params = self._get_regime_params()

        self.entry_price = price
        self.entry_bar = engine.current_index
        self.trade_direction = direction
        self.trailing_stop = None

        if direction == 'long':
            self.stop_price = price - self.current_atr * params['stop_atr_mult']
            self.target_price = price + self.current_atr * params['target_atr_mult']
            engine.buy(params['position_size'])
        else:
            self.stop_price = price + self.current_atr * params['stop_atr_mult']
            self.target_price = price - self.current_atr * params['target_atr_mult']
            engine.sell(params['position_size'])

    def _manage_position(self, engine, bar) -> bool:
        """Manage existing position with regime-aware exits."""
        if engine.position.is_flat:
            return False

        params = self._get_regime_params()
        bars_held = engine.current_index - self.entry_bar

        # Time exit
        if bars_held >= self.max_hold_bars:
            engine.close_position()
            self._reset()
            return True

        if self.trade_direction == 'long':
            # Stop loss
            if bar.low <= self.stop_price:
                engine.close_position()
                self._reset()
                return True

            # Take profit
            if bar.high >= self.target_price:
                engine.close_position()
                self._reset()
                return True

            # Trailing stop (only in trending regimes)
            if params['use_trailing']:
                if self.trailing_stop is not None:
                    self.trailing_stop = max(
                        self.trailing_stop,
                        bar.close - self.current_atr * 1.0
                    )
                    if bar.low <= self.trailing_stop:
                        engine.close_position()
                        self._reset()
                        return True
                else:
                    profit = bar.close - self.entry_price
                    if profit >= self.current_atr * params['trail_trigger_atr']:
                        self.trailing_stop = bar.close - self.current_atr * 1.0

        elif self.trade_direction == 'short':
            # Stop loss
            if bar.high >= self.stop_price:
                engine.close_position()
                self._reset()
                return True

            # Take profit
            if bar.low <= self.target_price:
                engine.close_position()
                self._reset()
                return True

            # Trailing stop
            if params['use_trailing']:
                if self.trailing_stop is not None:
                    self.trailing_stop = min(
                        self.trailing_stop,
                        bar.close + self.current_atr * 1.0
                    )
                    if bar.high >= self.trailing_stop:
                        engine.close_position()
                        self._reset()
                        return True
                else:
                    profit = self.entry_price - bar.close
                    if profit >= self.current_atr * params['trail_trigger_atr']:
                        self.trailing_stop = bar.close + self.current_atr * 1.0

        return False

    def _reset(self):
        """Reset trade state."""
        self.entry_price = None
        self.entry_bar = None
        self.stop_price = None
        self.target_price = None
        self.trailing_stop = None
        self.trade_direction = None

    def on_bar(self, engine, bar):
        """Process each bar."""
        self.highs.append(bar.high)
        self.lows.append(bar.low)
        self.closes.append(bar.close)
        self.volumes.append(bar.volume)

        # Skip low volume
        if bar.volume < self.min_volume:
            return

        # Need enough data
        min_bars = max(
            self.regime_detector.trend_ema_period + 5,
            self.rsi_period + 1,
            self.atr_period + 1,
            self.bb_period + 1,
        )
        if len(self.closes) < min_bars:
            return

        # Detect regime
        regime, confidence, details = self.regime_detector.detect_regime(
            self.closes, self.highs, self.lows
        )
        self.current_regime = regime

        # Calculate indicators
        rsi = Indicator.rsi(self.closes, self.rsi_period)
        atr = Indicator.atr(self.highs, self.lows, self.closes, self.atr_period)
        bb = Indicator.bollinger_bands(self.closes, self.bb_period, self.bb_std)

        if rsi is None or atr is None:
            return

        self.current_atr = atr

        # Manage existing position
        if not engine.position.is_flat:
            self._manage_position(engine, bar)
            return

        # Check for entries based on regime
        params = self._get_regime_params()

        if regime == Regime.BULL:
            if self._check_bull_entry(bar, rsi, atr):
                self._enter_trade(engine, 'long', bar.close)

        elif regime == Regime.BEAR:
            if self._check_bear_entry(bar, rsi, atr):
                self._enter_trade(engine, 'short', bar.close)

        elif regime == Regime.NEUTRAL:
            signal = self._check_neutral_entry(bar, rsi, bb)
            if signal:
                self._enter_trade(engine, signal, bar.close)


def run_backtest():
    """Run the regime-adaptive scalp backtest."""
    from backtest.engine import BacktestEngine

    data_path = Path(__file__).parent.parent.parent / "data" / "es" / "ES_combined_5min.parquet"
    data = pd.read_parquet(data_path)
    data = data[data['volume'] > 0].copy()

    print(f"Loaded {len(data)} bars")
    print(f"Date range: {data.index.min()} to {data.index.max()}")

    engine = BacktestEngine(
        data=data,
        initial_capital=100000.0,
        commission_per_contract=2.25,
        slippage_ticks=1,
        max_position=2,
    )

    strategy = ESScalpRegimeStrategy(
        regime_ema_period=50,
        regime_confirmation=3,
        rsi_period=7,
        atr_period=14,
        bb_period=20,
        bb_std=2.0,
        max_hold_bars=12,
        min_volume=100,
    )

    results = engine.run(strategy)
    return results, engine


if __name__ == "__main__":
    results, engine = run_backtest()

    print("\n" + "="*60)
    print("ES Scalp Regime-Adaptive Strategy Results")
    print("="*60)
    print(f"Initial Capital:  ${results['initial_capital']:,.2f}")
    print(f"Final Equity:     ${results['final_equity']:,.2f}")
    print(f"Total P&L:        ${results['total_pnl']:,.2f}")
    print(f"Total Return:     {results['total_return_pct']:.2f}%")
    print(f"Total Trades:     {results['total_trades']}")
    print(f"Win Rate:         {results['win_rate']:.2f}%")
    print(f"Avg Win:          ${results['avg_win']:,.2f}")
    print(f"Avg Loss:         ${results['avg_loss']:,.2f}")
    print(f"Profit Factor:    {results['profit_factor']:.2f}")
    print(f"Max Drawdown:     {results['max_drawdown']:.2f}%")
    print(f"Sharpe Ratio:     {results['sharpe_ratio']:.2f}")

    if len(results['trades']) > 0:
        print(f"\nAvg Bars Held:    {results['trades']['bars_held'].mean():.1f} bars")
        print(f"                  {results['trades']['bars_held'].mean() * 5:.1f} minutes")
