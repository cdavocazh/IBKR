#!/usr/bin/env python3
"""
Technical Analysis Agent - Main Runner

Runs comprehensive technical analysis on futures data and generates
a markdown report with datetime in the filename.

Usage:
    python run_analysis.py                    # Analyze ES (default)
    python run_analysis.py --symbol ES        # Analyze ES
    python run_analysis.py --symbol GC        # Analyze GC
    python run_analysis.py --symbol SI        # Analyze SI
    python run_analysis.py --timeframe 5min   # Use 5-minute data
    python run_analysis.py --bars 500         # Use last 500 bars
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime

import pandas as pd

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from TA_agent.analyzer import TAAnalyzer
from TA_agent.report import ReportGenerator


def load_data(symbol: str, timeframe: str = "5min") -> pd.DataFrame:
    """Load price data for the specified symbol."""
    data_dir = Path(__file__).parent.parent / "data"

    # Map symbol to data file
    file_map = {
        "ES": {
            "5min": data_dir / "es" / "ES_combined_5min.parquet",
            "1min": data_dir / "es" / "ES_1min.parquet",
        },
        "GC": {
            "5min": data_dir / "gc" / "GC_combined_5mins.parquet",
            "1min": data_dir / "gc" / "GC_1min.parquet",
        },
        "SI": {
            "5min": data_dir / "si" / "SI_combined_5mins.parquet",
            "1min": data_dir / "si" / "SI_1min.parquet",
        },
    }

    symbol = symbol.upper()
    if symbol not in file_map:
        raise ValueError(f"Unknown symbol: {symbol}. Available: {list(file_map.keys())}")

    if timeframe not in file_map[symbol]:
        raise ValueError(f"Unknown timeframe: {timeframe}. Available: {list(file_map[symbol].keys())}")

    filepath = file_map[symbol][timeframe]
    if not filepath.exists():
        raise FileNotFoundError(f"Data file not found: {filepath}")

    data = pd.read_parquet(filepath)

    # Filter out zero volume bars
    data = data[data['volume'] > 0].copy()

    return data


def run_analysis(
    symbol: str = "ES",
    timeframe: str = "5min",
    bars: int = 500,
    output_dir: str = None
) -> str:
    """
    Run technical analysis and generate report.

    Args:
        symbol: Instrument symbol (ES, GC, SI)
        timeframe: Data timeframe (5min, 1min)
        bars: Number of bars to analyze
        output_dir: Directory for output report

    Returns:
        Path to generated report
    """
    print(f"\n{'='*60}")
    print(f"  Technical Analysis Agent")
    print(f"{'='*60}")
    print(f"Symbol:    {symbol}")
    print(f"Timeframe: {timeframe}")
    print(f"Bars:      {bars}")
    print(f"{'='*60}\n")

    # Load data
    print("Loading data...")
    data = load_data(symbol, timeframe)

    # Use last N bars
    if len(data) > bars:
        data = data.tail(bars)

    print(f"Loaded {len(data)} bars")
    print(f"Date range: {data.index.min()} to {data.index.max()}")
    print(f"Current price: {data['close'].iloc[-1]:,.2f}")
    print()

    # Run analysis
    print("Running technical analysis...")
    analyzer = TAAnalyzer(data, symbol=symbol, timeframe=timeframe)
    analysis = analyzer.analyze()

    # Print summary
    print(f"\n{'='*60}")
    print(f"  Analysis Summary")
    print(f"{'='*60}")
    print(f"Overall Bias: {analysis.overall_bias.upper()} (Strength: {analysis.bias_strength}%)")
    print()

    bullish = sum(1 for s in analysis.signals if s.signal == "bullish")
    bearish = sum(1 for s in analysis.signals if s.signal == "bearish")
    neutral = sum(1 for s in analysis.signals if s.signal == "neutral")

    print(f"Signals: {bullish} bullish, {bearish} bearish, {neutral} neutral")
    print()

    print("Key Observations:")
    for obs in analysis.key_observations:
        print(f"  - {obs}")
    print()

    if analysis.support_levels:
        print(f"Support levels: {', '.join(f'{s:,.2f}' for s in analysis.support_levels[:3])}")
    if analysis.resistance_levels:
        print(f"Resistance levels: {', '.join(f'{r:,.2f}' for r in analysis.resistance_levels[:3])}")
    print()

    # Generate report
    print("Generating report...")
    generator = ReportGenerator(output_dir)
    report_path = generator.generate(analysis)

    print(f"\n{'='*60}")
    print(f"  Report Generated")
    print(f"{'='*60}")
    print(f"File: {report_path}")
    print()

    return report_path


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Technical Analysis Agent - Generate TA reports for futures"
    )
    parser.add_argument(
        "--symbol", "-s",
        type=str,
        default="ES",
        choices=["ES", "GC", "SI"],
        help="Symbol to analyze (default: ES)"
    )
    parser.add_argument(
        "--timeframe", "-t",
        type=str,
        default="5min",
        choices=["5min", "1min"],
        help="Data timeframe (default: 5min)"
    )
    parser.add_argument(
        "--bars", "-b",
        type=int,
        default=500,
        help="Number of bars to analyze (default: 500)"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output directory for report"
    )

    args = parser.parse_args()

    try:
        report_path = run_analysis(
            symbol=args.symbol,
            timeframe=args.timeframe,
            bars=args.bars,
            output_dir=args.output
        )
        print(f"Analysis complete. Report saved to: {report_path}")
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
