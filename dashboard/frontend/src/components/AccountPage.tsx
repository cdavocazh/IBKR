import { useState } from 'react'
import { useParams } from 'react-router-dom'
import type { MultiAccountPortfolio, NewsHeadline, PortfolioSummary } from '../types'
import { PortfolioSummaryCards } from './PortfolioSummary'
import { PortfolioTable } from './PortfolioTable'
import { NewsFeed } from './NewsFeed'
import { OrdersTable } from './OrdersTable'
import { PriceChart } from './PriceChart'
import { SentimentPanel } from './SentimentPanel'

const emptySummary: PortfolioSummary = {
  total_market_value: 0,
  total_unrealized_pnl: 0,
  total_realized_pnl: 0,
  total_pnl_pct: null,
  position_count: 0,
  net_liquidation: null,
  available_funds: null,
  maint_margin_req: null,
  last_update: null,
}

interface Props {
  multiPortfolio: MultiAccountPortfolio
  headlines: NewsHeadline[]
  liveMode: boolean
}

export function AccountPage({ multiPortfolio, headlines, liveMode }: Props) {
  const { accountId } = useParams<{ accountId: string }>()
  const [chartConId, setChartConId] = useState<number | null>(null)

  const portfolio = accountId ? multiPortfolio.portfolios[accountId] : undefined
  const summary = portfolio?.summary || emptySummary
  const positions = portfolio?.positions || []
  const orders = accountId ? multiPortfolio.orders?.[accountId] || [] : []

  // Look up the latest position data on every render so the chart header stays live
  const chartPosition = chartConId != null
    ? positions.find((p) => p.con_id === chartConId) ?? null
    : null

  return (
    <div className="flex flex-1 flex-col gap-4 overflow-auto p-4 lg:flex-row lg:p-6">
      {/* Left: Portfolio */}
      <div className="flex flex-col gap-4 lg:w-3/5">
        <div className="flex items-center gap-3">
          <h2 className="text-base font-semibold text-gray-300 font-mono">{accountId}</h2>
          <span className="rounded bg-gray-800 px-2 py-0.5 text-xs text-gray-500">
            {positions.length} position{positions.length !== 1 ? 's' : ''}
          </span>
        </div>
        <PortfolioSummaryCards summary={summary} />
        {orders.length > 0 && (
          <>
            <div className="text-xs font-semibold uppercase tracking-wider text-gray-500">
              Open Orders ({orders.length})
            </div>
            <OrdersTable orders={orders} />
          </>
        )}
        <PortfolioTable
          positions={positions}
          liveMode={liveMode}
          onSymbolClick={(p) => setChartConId(p.con_id)}
        />
      </div>

      {/* Right: Sentiment + News */}
      <div className="flex flex-col gap-4 lg:w-2/5">
        <SentimentPanel />
        <NewsFeed headlines={headlines} />
      </div>

      {/* Chart Modal */}
      {chartPosition && (
        <PriceChart
          position={chartPosition}
          onClose={() => setChartConId(null)}
          liveMode={liveMode}
        />
      )}
    </div>
  )
}
