"""Backtesting Framework for ES Futures"""

from .engine import BacktestEngine
from .strategy import Strategy
from .analytics import PerformanceAnalytics
from .regime import RegimeDetector, MarketRegime, RegimeIndicators
from .regime_strategies import (
    BuyTheDipStrategy,
    SellTheRipStrategy,
    MeanReversionExtremesStrategy,
    AdaptiveRegimeStrategy,
)

__all__ = [
    "BacktestEngine",
    "Strategy",
    "PerformanceAnalytics",
    "RegimeDetector",
    "MarketRegime",
    "RegimeIndicators",
    "BuyTheDipStrategy",
    "SellTheRipStrategy",
    "MeanReversionExtremesStrategy",
    "AdaptiveRegimeStrategy",
]
