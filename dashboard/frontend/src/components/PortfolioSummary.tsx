import type { PortfolioSummary as Summary } from '../types'

const fmt = (v: number | null, decimals = 2) =>
  v != null
    ? v.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
    : '---'

const fmtUsd = (v: number | null) => (v != null ? `$${fmt(v)}` : '---')

const pnlColor = (v: number | null) =>
  v == null ? 'text-gray-400' : v >= 0 ? 'text-emerald-400' : 'text-red-400'

const pnlSign = (v: number | null) => (v != null && v >= 0 ? '+' : '')

interface Props {
  summary: Summary
}

export function PortfolioSummaryCards({ summary }: Props) {
  const cards = [
    { label: 'Net Liquidation', value: fmtUsd(summary.net_liquidation), color: 'text-white' },
    {
      label: 'Unrealized P&L',
      value: `${pnlSign(summary.total_unrealized_pnl)}${fmtUsd(summary.total_unrealized_pnl)}`,
      color: pnlColor(summary.total_unrealized_pnl),
      sub:
        summary.total_pnl_pct != null
          ? `${pnlSign(summary.total_pnl_pct)}${fmt(summary.total_pnl_pct)}%`
          : undefined,
    },
    {
      label: 'Realized P&L',
      value: `${pnlSign(summary.total_realized_pnl)}${fmtUsd(summary.total_realized_pnl)}`,
      color: pnlColor(summary.total_realized_pnl),
    },
    { label: 'Market Value', value: fmtUsd(summary.total_market_value), color: 'text-white' },
    { label: 'Positions', value: String(summary.position_count), color: 'text-white' },
    { label: 'Available Funds', value: fmtUsd(summary.available_funds), color: 'text-white' },
    { label: 'Maint. Margin', value: fmtUsd(summary.maint_margin_req), color: 'text-yellow-400' },
  ]

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
      {cards.map((c) => (
        <div
          key={c.label}
          className="rounded-lg border border-gray-700/50 bg-gray-800/60 p-4"
        >
          <div className="text-xs uppercase tracking-wide text-gray-500">{c.label}</div>
          <div className={`mt-1 text-lg font-semibold ${c.color}`}>{c.value}</div>
          {c.sub && (
            <div className={`text-sm ${pnlColor(summary.total_pnl_pct)}`}>{c.sub}</div>
          )}
        </div>
      ))}
    </div>
  )
}
