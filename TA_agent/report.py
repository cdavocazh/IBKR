"""
Technical Analysis Report Generator

Generates markdown reports with datetime in filename.
"""

from datetime import datetime
from pathlib import Path
from typing import List, Optional
from .analyzer import TAAnalysis, TASignal


class ReportGenerator:
    """Generate markdown technical analysis reports."""

    def __init__(self, output_dir: Optional[str] = None):
        """
        Initialize report generator.

        Args:
            output_dir: Directory to save reports (default: TA_agent/reports)
        """
        if output_dir:
            self.output_dir = Path(output_dir)
        else:
            self.output_dir = Path(__file__).parent / "reports"

        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, analysis: TAAnalysis) -> str:
        """
        Generate markdown report and save to file.

        Args:
            analysis: TAAnalysis object with results

        Returns:
            Path to generated report file
        """
        # Generate filename with datetime (HH:MM)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"{analysis.symbol}_TA_{timestamp}.md"
        filepath = self.output_dir / filename

        # Build report content
        content = self._build_report(analysis)

        # Write to file
        with open(filepath, 'w') as f:
            f.write(content)

        return str(filepath)

    def _build_report(self, analysis: TAAnalysis) -> str:
        """Build the markdown report content."""
        lines = []

        # Header
        lines.append(f"# {analysis.symbol} Technical Analysis Report")
        lines.append("")
        lines.append(f"**Generated:** {analysis.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**Timeframe:** {analysis.timeframe}")
        lines.append(f"**Current Price:** {analysis.current_price:,.2f}")
        lines.append("")

        # Overall Bias
        lines.append("---")
        lines.append("")
        lines.append("## Overall Market Bias")
        lines.append("")

        bias_emoji = self._get_bias_emoji(analysis.overall_bias)
        lines.append(f"### {bias_emoji} {analysis.overall_bias.upper()}")
        lines.append(f"**Conviction Strength:** {analysis.bias_strength}%")
        lines.append("")

        # Bias meter
        lines.append(self._create_bias_meter(analysis.overall_bias, analysis.bias_strength))
        lines.append("")

        # Key Observations
        if analysis.key_observations:
            lines.append("### Key Observations")
            lines.append("")
            for obs in analysis.key_observations:
                lines.append(f"- {obs}")
            lines.append("")

        # Support/Resistance
        lines.append("---")
        lines.append("")
        lines.append("## Support & Resistance Levels")
        lines.append("")

        lines.append("### Resistance Levels")
        if analysis.resistance_levels:
            for i, level in enumerate(analysis.resistance_levels, 1):
                distance = ((level - analysis.current_price) / analysis.current_price) * 100
                lines.append(f"- **R{i}:** {level:,.2f} (+{distance:.2f}%)")
        else:
            lines.append("- No significant resistance levels identified")
        lines.append("")

        lines.append(f"**Current Price: {analysis.current_price:,.2f}**")
        lines.append("")

        lines.append("### Support Levels")
        if analysis.support_levels:
            for i, level in enumerate(analysis.support_levels, 1):
                distance = ((analysis.current_price - level) / analysis.current_price) * 100
                lines.append(f"- **S{i}:** {level:,.2f} (-{distance:.2f}%)")
        else:
            lines.append("- No significant support levels identified")
        lines.append("")

        # Signal Summary Table
        lines.append("---")
        lines.append("")
        lines.append("## Signal Summary")
        lines.append("")

        # Group by category
        for category in ['trend', 'momentum', 'volatility', 'volume']:
            cat_signals = [s for s in analysis.signals if s.category == category]
            if cat_signals:
                lines.append(f"### {category.title()} Indicators")
                lines.append("")
                lines.append("| Indicator | Signal | Strength | Value | Description |")
                lines.append("|-----------|--------|----------|-------|-------------|")

                for signal in cat_signals:
                    emoji = self._get_signal_emoji(signal.signal)
                    strength_bar = self._create_strength_bar(signal.strength)
                    value_str = f"{signal.value:.2f}" if isinstance(signal.value, float) else str(signal.value)
                    lines.append(
                        f"| {signal.indicator} | {emoji} {signal.signal} | {strength_bar} {signal.strength}% | {value_str} | {signal.description} |"
                    )
                lines.append("")

        # Detailed Analysis
        lines.append("---")
        lines.append("")
        lines.append("## Detailed Indicator Analysis")
        lines.append("")

        for category in ['trend', 'momentum', 'volatility', 'volume']:
            cat_signals = [s for s in analysis.signals if s.category == category]
            if cat_signals:
                lines.append(f"### {category.title()}")
                lines.append("")

                for signal in cat_signals:
                    emoji = self._get_signal_emoji(signal.signal)
                    lines.append(f"**{signal.indicator}** {emoji}")
                    lines.append(f"- Signal: {signal.signal.upper()}")
                    lines.append(f"- Strength: {signal.strength}%")
                    lines.append(f"- {signal.description}")
                    lines.append("")

        # Trading Implications
        lines.append("---")
        lines.append("")
        lines.append("## Trading Implications")
        lines.append("")

        bullish_signals = [s for s in analysis.signals if s.signal == "bullish"]
        bearish_signals = [s for s in analysis.signals if s.signal == "bearish"]

        if analysis.overall_bias == "bullish":
            lines.append("### Bullish Setup")
            lines.append("")
            lines.append("**Entry Consideration:** Look for pullbacks to support levels")
            lines.append("")
            if analysis.support_levels:
                lines.append(f"- Primary support: {analysis.support_levels[0]:,.2f}")
                if len(analysis.support_levels) > 1:
                    lines.append(f"- Secondary support: {analysis.support_levels[1]:,.2f}")
            lines.append("")
            lines.append("**Key Bullish Signals:**")
            for signal in sorted(bullish_signals, key=lambda x: x.strength, reverse=True)[:5]:
                lines.append(f"- {signal.indicator}: {signal.description}")

        elif analysis.overall_bias == "bearish":
            lines.append("### Bearish Setup")
            lines.append("")
            lines.append("**Entry Consideration:** Look for rallies to resistance levels")
            lines.append("")
            if analysis.resistance_levels:
                lines.append(f"- Primary resistance: {analysis.resistance_levels[0]:,.2f}")
                if len(analysis.resistance_levels) > 1:
                    lines.append(f"- Secondary resistance: {analysis.resistance_levels[1]:,.2f}")
            lines.append("")
            lines.append("**Key Bearish Signals:**")
            for signal in sorted(bearish_signals, key=lambda x: x.strength, reverse=True)[:5]:
                lines.append(f"- {signal.indicator}: {signal.description}")

        else:
            lines.append("### Neutral/Ranging Market")
            lines.append("")
            lines.append("**Approach:** Wait for clearer direction or trade the range")
            lines.append("")
            if analysis.support_levels and analysis.resistance_levels:
                lines.append(f"- Range bottom: {analysis.support_levels[0]:,.2f}")
                lines.append(f"- Range top: {analysis.resistance_levels[0]:,.2f}")
            lines.append("")
            lines.append("**Mixed Signals:**")
            lines.append(f"- Bullish indicators: {len(bullish_signals)}")
            lines.append(f"- Bearish indicators: {len(bearish_signals)}")

        lines.append("")

        # Disclaimer
        lines.append("---")
        lines.append("")
        lines.append("*This analysis is for informational purposes only. Always use proper risk management.*")
        lines.append("")

        return "\n".join(lines)

    def _get_bias_emoji(self, bias: str) -> str:
        """Get emoji for bias."""
        if bias == "bullish":
            return "🟢"
        elif bias == "bearish":
            return "🔴"
        else:
            return "🟡"

    def _get_signal_emoji(self, signal: str) -> str:
        """Get emoji for signal."""
        if signal == "bullish":
            return "🟢"
        elif signal == "bearish":
            return "🔴"
        else:
            return "⚪"

    def _create_bias_meter(self, bias: str, strength: int) -> str:
        """Create a visual bias meter."""
        total_bars = 20
        if bias == "bullish":
            filled = int((strength / 100) * (total_bars // 2))
            meter = "⬜" * (total_bars // 2) + "│" + "🟩" * filled + "⬜" * (total_bars // 2 - filled)
        elif bias == "bearish":
            filled = int((strength / 100) * (total_bars // 2))
            meter = "⬜" * (total_bars // 2 - filled) + "🟥" * filled + "│" + "⬜" * (total_bars // 2)
        else:
            meter = "⬜" * (total_bars // 2) + "│" + "⬜" * (total_bars // 2)

        return f"```\nBearish [{meter}] Bullish\n```"

    def _create_strength_bar(self, strength: int) -> str:
        """Create a small strength indicator."""
        if strength >= 80:
            return "████"
        elif strength >= 60:
            return "███░"
        elif strength >= 40:
            return "██░░"
        elif strength >= 20:
            return "█░░░"
        else:
            return "░░░░"
