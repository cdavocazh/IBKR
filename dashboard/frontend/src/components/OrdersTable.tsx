import type { Order } from '../types'

const fmt = (v: number | null, d = 2) =>
  v != null ? v.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d }) : '---'

const statusColor = (s: string) => {
  switch (s) {
    case 'Submitted':
    case 'PreSubmitted':
      return 'text-blue-400'
    case 'Filled':
      return 'text-emerald-400'
    case 'Cancelled':
    case 'Inactive':
      return 'text-gray-500'
    case 'PendingSubmit':
    case 'PendingCancel':
      return 'text-yellow-400'
    default:
      return 'text-gray-300'
  }
}

const actionColor = (a: string) =>
  a === 'BUY' ? 'text-emerald-400' : 'text-red-400'

interface Props {
  orders: Order[]
}

export function OrdersTable({ orders }: Props) {
  if (orders.length === 0) {
    return (
      <div className="rounded-lg border border-gray-700/50 bg-gray-800/30 px-4 py-6 text-center text-sm text-gray-600">
        No open orders
      </div>
    )
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-700/50">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-700/50 bg-gray-800/80 text-gray-400">
            <th className="px-3 py-2 text-left font-medium">Symbol</th>
            <th className="px-3 py-2 text-left font-medium">Action</th>
            <th className="px-3 py-2 text-left font-medium">Type</th>
            <th className="px-3 py-2 text-right font-medium">Qty</th>
            <th className="px-3 py-2 text-right font-medium">Limit</th>
            <th className="px-3 py-2 text-right font-medium">Stop</th>
            <th className="px-3 py-2 text-left font-medium">Status</th>
            <th className="px-3 py-2 text-right font-medium">Filled</th>
            <th className="px-3 py-2 text-left font-medium">TIF</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((o) => (
            <tr
              key={o.perm_id || o.order_id}
              className="border-b border-gray-800/50 transition-colors hover:bg-gray-800/40"
            >
              <td className="px-3 py-2 font-mono font-medium text-white">{o.local_symbol}</td>
              <td className={`px-3 py-2 font-bold ${actionColor(o.action)}`}>{o.action}</td>
              <td className="px-3 py-2 text-gray-300">{o.order_type}</td>
              <td className="px-3 py-2 text-right font-mono">{o.total_qty}</td>
              <td className="px-3 py-2 text-right font-mono">
                {o.limit_price != null ? `$${fmt(o.limit_price)}` : '---'}
              </td>
              <td className="px-3 py-2 text-right font-mono">
                {o.aux_price != null ? `$${fmt(o.aux_price)}` : '---'}
              </td>
              <td className={`px-3 py-2 font-medium ${statusColor(o.status)}`}>{o.status}</td>
              <td className="px-3 py-2 text-right font-mono text-gray-400">
                {o.filled}/{o.total_qty}
              </td>
              <td className="px-3 py-2 text-gray-500">{o.tif}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
