import { NavLink } from 'react-router-dom'
import type { MultiAccountPortfolio, WatchlistSummary } from '../types'

const fmtUsd = (v: number | null | undefined) =>
  v != null
    ? `$${v.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
    : '---'

interface Props {
  multiPortfolio: MultiAccountPortfolio
  watchlists: WatchlistSummary[]
  onCreateWatchlist: () => void
}

export function AccountSidebar({ multiPortfolio, watchlists, onCreateWatchlist }: Props) {
  const { accounts, portfolios } = multiPortfolio

  return (
    <nav className="flex w-52 shrink-0 flex-col border-r border-gray-800 bg-gray-900/60 overflow-y-auto">
      <div className="px-4 py-3 text-xs font-semibold uppercase tracking-wider text-gray-500">
        Accounts
      </div>
      <div className="flex flex-col gap-0.5 px-2">
        {accounts.length === 0 && (
          <div className="px-2 py-3 text-sm text-gray-600">No accounts</div>
        )}
        {accounts.map((acctId) => {
          const portfolio = portfolios[acctId]
          const netLiq = portfolio?.summary?.net_liquidation
          return (
            <NavLink
              key={acctId}
              to={`/account/${acctId}`}
              className={({ isActive }) =>
                `rounded-md px-3 py-2.5 transition-colors ${
                  isActive
                    ? 'bg-blue-600/20 text-blue-400 border border-blue-500/30'
                    : 'text-gray-300 hover:bg-gray-800/60 hover:text-white border border-transparent'
                }`
              }
            >
              <div className="text-sm font-medium font-mono">{acctId}</div>
              <div className="mt-0.5 text-xs text-gray-500">{fmtUsd(netLiq)}</div>
            </NavLink>
          )
        })}
      </div>

      {/* Watchlists */}
      <div className="mt-4 border-t border-gray-800 pt-2">
        <div className="flex items-center justify-between px-4 py-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-gray-500">
            Watchlists
          </span>
          <button
            onClick={onCreateWatchlist}
            className="rounded px-1.5 py-0.5 text-xs text-gray-500 hover:bg-gray-800 hover:text-white"
            title="Create watchlist"
          >
            +
          </button>
        </div>
        <div className="flex flex-col gap-0.5 px-2 pb-2">
          {watchlists.length === 0 && (
            <div className="px-2 py-2 text-xs text-gray-600">No watchlists</div>
          )}
          {watchlists.map((wl) => (
            <NavLink
              key={wl.id}
              to={`/watchlist/${wl.id}`}
              className={({ isActive }) =>
                `rounded-md px-3 py-2 transition-colors ${
                  isActive
                    ? 'bg-blue-600/20 text-blue-400 border border-blue-500/30'
                    : 'text-gray-300 hover:bg-gray-800/60 hover:text-white border border-transparent'
                }`
              }
            >
              <div className="text-sm">{wl.name}</div>
              <div className="mt-0.5 text-xs text-gray-500">{wl.count} instrument{wl.count !== 1 ? 's' : ''}</div>
            </NavLink>
          ))}
        </div>
      </div>
    </nav>
  )
}
