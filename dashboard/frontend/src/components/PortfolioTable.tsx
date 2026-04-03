import { useState, useMemo } from 'react'
import type { Position } from '../types'

const fmt = (v: number | null, d = 2) =>
  v != null ? v.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d }) : '---'

const pnlCls = (v: number | null) =>
  v == null ? 'text-gray-500' : v >= 0 ? 'text-emerald-400' : 'text-red-400'

const priceCls = (current: number | null, prevClose: number | null) => {
  if (current == null || prevClose == null) return 'text-gray-300'
  return current >= prevClose ? 'text-emerald-400' : 'text-red-400'
}

const fmtExpiry = (d: string | null) => {
  if (!d || d.length < 8) return d || '---'
  return `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}`
}

type SortKey = keyof Position
type SortDir = 'asc' | 'desc'

const SEC_TYPES = ['ALL', 'STK', 'OPT', 'FUT', 'FOP', 'WAR', 'CASH', 'ETF'] as const

interface Props {
  positions: Position[]
  liveMode?: boolean
  onSymbolClick?: (position: Position) => void
}

export function PortfolioTable({ positions, liveMode, onSymbolClick }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('unrealized_pnl')
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [typeFilter, setTypeFilter] = useState<string>('ALL')

  // Detect if any position is an option/FOP
  const hasOptions = positions.some((p) => p.sec_type === 'OPT' || p.sec_type === 'FOP')

  // Get unique sec_types present
  const presentTypes = useMemo(() => {
    const types = new Set(positions.map((p) => p.sec_type))
    return SEC_TYPES.filter((t) => t === 'ALL' || types.has(t))
  }, [positions])

  const filtered = useMemo(() => {
    if (typeFilter === 'ALL') return positions
    return positions.filter((p) => p.sec_type === typeFilter)
  }, [positions, typeFilter])

  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      const av = a[sortKey] ?? -Infinity
      const bv = b[sortKey] ?? -Infinity
      if (av < bv) return sortDir === 'asc' ? -1 : 1
      if (av > bv) return sortDir === 'asc' ? 1 : -1
      return 0
    })
  }, [filtered, sortKey, sortDir])

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  const arrow = (key: SortKey) =>
    sortKey === key ? (sortDir === 'asc' ? ' \u25B2' : ' \u25BC') : ''

  type Col = { key: SortKey; label: string; align?: string; show?: boolean }
  const cols: Col[] = [
    { key: 'local_symbol', label: 'Symbol' },
    { key: 'sec_type', label: 'Type' },
    { key: 'right', label: 'P/C', show: hasOptions },
    { key: 'strike', label: 'Strike', align: 'text-right', show: hasOptions },
    { key: 'expiry', label: 'Expiry', show: hasOptions },
    { key: 'position_size', label: 'Pos', align: 'text-right' },
    { key: 'avg_cost', label: 'Avg Cost', align: 'text-right' },
    { key: 'current_price', label: liveMode ? 'Current (LIVE)' : 'Current', align: 'text-right' },
    { key: 'prev_close', label: 'Prev Close', align: 'text-right' },
    { key: 'market_value', label: 'Mkt Value', align: 'text-right' },
    { key: 'daily_pnl', label: "Day P&L", align: 'text-right' },
    { key: 'unrealized_pnl', label: 'Unreal P&L', align: 'text-right' },
    { key: 'pnl_pct', label: 'P&L %', align: 'text-right' },
  ]

  const visibleCols = cols.filter((c) => c.show !== false)

  // Compute daily totals
  const totalDailyPnl = filtered.reduce((sum, p) => sum + (p.daily_pnl ?? 0), 0)

  return (
    <div>
      {/* Type filter */}
      {presentTypes.length > 2 && (
        <div className="mb-2 flex items-center gap-1">
          <span className="mr-1 text-xs text-gray-500">Filter:</span>
          {presentTypes.map((t) => (
            <button
              key={t}
              onClick={() => setTypeFilter(t)}
              className={`rounded px-2 py-0.5 text-xs font-medium transition-colors ${
                typeFilter === t
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-300'
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      )}

      {/* Daily P&L banner */}
      {totalDailyPnl !== 0 && (
        <div className={`mb-2 flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm font-mono ${
          totalDailyPnl >= 0
            ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
            : 'border-red-500/30 bg-red-500/10 text-red-400'
        }`}>
          <span className="text-xs text-gray-400 font-sans">Today:</span>
          {totalDailyPnl >= 0 ? '+' : ''}${fmt(totalDailyPnl)}
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-gray-700/50">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-700/50 bg-gray-800/80 text-gray-400">
              {visibleCols.map((c) => (
                <th
                  key={c.key}
                  className={`cursor-pointer whitespace-nowrap px-3 py-2 font-medium select-none ${c.align || 'text-left'}`}
                  onClick={() => toggleSort(c.key)}
                >
                  {c.label}
                  {arrow(c.key)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((p, i) => (
              <tr
                key={`${p.local_symbol}-${p.account}-${i}`}
                className="border-b border-gray-800/50 transition-colors hover:bg-gray-800/40"
              >
                <td
                  className="px-3 py-2 font-mono font-medium text-blue-400 cursor-pointer hover:text-blue-300 hover:underline"
                  onClick={() => onSymbolClick?.(p)}
                >{p.local_symbol}</td>
                <td className="px-3 py-2 text-gray-400">{p.sec_type}</td>
                {hasOptions && (
                  <td className="px-3 py-2 text-gray-400">
                    {p.right === 'C' ? (
                      <span className="text-emerald-400">Call</span>
                    ) : p.right === 'P' ? (
                      <span className="text-red-400">Put</span>
                    ) : '---'}
                  </td>
                )}
                {hasOptions && (
                  <td className="px-3 py-2 text-right font-mono">
                    {p.strike ? `$${fmt(p.strike)}` : '---'}
                  </td>
                )}
                {hasOptions && (
                  <td className="px-3 py-2 text-gray-400 font-mono text-xs">
                    {fmtExpiry(p.expiry)}
                  </td>
                )}
                <td className="px-3 py-2 text-right font-mono">{p.position_size}</td>
                <td className="px-3 py-2 text-right font-mono">${fmt(p.avg_cost)}</td>
                <td className={`px-3 py-2 text-right font-mono ${priceCls(p.current_price, p.prev_close)}`}>
                  {p.current_price != null ? `$${fmt(p.current_price)}` : '---'}
                </td>
                <td className="px-3 py-2 text-right font-mono text-gray-400">
                  {p.prev_close != null ? `$${fmt(p.prev_close)}` : '---'}
                </td>
                <td className="px-3 py-2 text-right font-mono">{p.market_value != null ? `$${fmt(p.market_value)}` : '---'}</td>
                <td className={`px-3 py-2 text-right font-mono ${pnlCls(p.daily_pnl)}`}>
                  {p.daily_pnl != null ? `${p.daily_pnl >= 0 ? '+' : ''}$${fmt(p.daily_pnl)}` : '---'}
                </td>
                <td className={`px-3 py-2 text-right font-mono ${pnlCls(p.unrealized_pnl)}`}>
                  {p.unrealized_pnl != null ? `${p.unrealized_pnl >= 0 ? '+' : ''}$${fmt(p.unrealized_pnl)}` : '---'}
                </td>
                <td className={`px-3 py-2 text-right font-mono ${pnlCls(p.pnl_pct)}`}>
                  {p.pnl_pct != null ? `${p.pnl_pct >= 0 ? '+' : ''}${fmt(p.pnl_pct)}%` : '---'}
                </td>
              </tr>
            ))}
            {sorted.length === 0 && (
              <tr>
                <td colSpan={visibleCols.length} className="px-3 py-8 text-center text-gray-500">
                  No positions
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
