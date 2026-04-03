import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import type { WatchlistInstrument } from '../types'
import { AddInstrumentModal } from './AddInstrumentModal'
import { authFetch } from '../config'

const fmt = (v: number | null | undefined, d = 2) =>
  v != null ? v.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d }) : '---'

const changeCls = (v: number | null | undefined) =>
  v == null ? 'text-gray-500' : v >= 0 ? 'text-emerald-400' : 'text-red-400'

interface Props {
  liveMode: boolean
  onWatchlistsChanged: () => void
}

export function WatchlistPage({ liveMode, onWatchlistsChanged }: Props) {
  const { watchlistId } = useParams<{ watchlistId: string }>()
  const navigate = useNavigate()
  const [instruments, setInstruments] = useState<WatchlistInstrument[]>([])
  const [name, setName] = useState('')
  const [editing, setEditing] = useState(false)
  const [editName, setEditName] = useState('')
  const [showAdd, setShowAdd] = useState(false)
  const [loading, setLoading] = useState(true)
  const intervalRef = useRef<ReturnType<typeof setInterval>>(undefined)

  const fetchInstruments = useCallback(async () => {
    if (!watchlistId) return
    try {
      const res = await authFetch(`/api/watchlists/${watchlistId}/instruments`)
      const data = await res.json()
      setInstruments(data.instruments || [])
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }, [watchlistId])

  // Fetch watchlist name
  useEffect(() => {
    (async () => {
      try {
        const res = await authFetch('/api/watchlists')
        const data = await res.json()
        const wl = data.watchlists?.find((w: { id: string }) => w.id === watchlistId)
        if (wl) setName(wl.name)
      } catch { /* ignore */ }
    })()
  }, [watchlistId])

  // Initial fetch + auto-refresh
  useEffect(() => {
    fetchInstruments()
    const interval = liveMode ? 2000 : 15000
    intervalRef.current = setInterval(fetchInstruments, interval)
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [fetchInstruments, liveMode])

  const handleRename = async () => {
    if (!editName.trim() || !watchlistId) return
    await authFetch(`/api/watchlists/${watchlistId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: editName.trim() }),
    })
    setName(editName.trim())
    setEditing(false)
    onWatchlistsChanged()
  }

  const handleDelete = async () => {
    if (!watchlistId) return
    await authFetch(`/api/watchlists/${watchlistId}`, { method: 'DELETE' })
    onWatchlistsChanged()
    navigate('/')
  }

  const handleRemove = async (inst: WatchlistInstrument) => {
    if (!watchlistId) return
    const id = inst.conId || inst.symbol
    await authFetch(`/api/watchlists/${watchlistId}/instruments/${id}`, { method: 'DELETE' })
    setInstruments((prev) => prev.filter((i) => i.symbol !== inst.symbol))
    onWatchlistsChanged()
  }

  return (
    <div className="flex flex-1 flex-col gap-4 overflow-auto p-4 lg:p-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        {editing ? (
          <form
            onSubmit={(e) => { e.preventDefault(); handleRename() }}
            className="flex items-center gap-2"
          >
            <input
              autoFocus
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
              onBlur={() => setEditing(false)}
              className="rounded border border-gray-600 bg-gray-800 px-2 py-1 text-base font-semibold text-white outline-none focus:border-blue-500"
            />
          </form>
        ) : (
          <h2
            className="cursor-pointer text-base font-semibold text-gray-300 hover:text-white"
            onClick={() => { setEditName(name); setEditing(true) }}
            title="Click to rename"
          >
            {name || 'Watchlist'}
          </h2>
        )}
        <span className="rounded bg-gray-800 px-2 py-0.5 text-xs text-gray-500">
          {instruments.length} instrument{instruments.length !== 1 ? 's' : ''}
        </span>
        <button
          onClick={() => setShowAdd(true)}
          className="rounded-md bg-blue-600 px-3 py-1 text-xs font-medium text-white hover:bg-blue-500"
        >
          + Add
        </button>
        <button
          onClick={handleDelete}
          className="rounded-md px-2 py-1 text-xs text-gray-500 hover:bg-red-500/20 hover:text-red-400"
        >
          Delete
        </button>
      </div>

      {/* Instruments Table */}
      {loading ? (
        <div className="py-8 text-center text-sm text-gray-500">Loading...</div>
      ) : instruments.length === 0 ? (
        <div className="rounded-lg border border-gray-700/50 bg-gray-800/30 px-4 py-8 text-center text-sm text-gray-600">
          No instruments — click "+ Add" to search and add
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-700/50">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-700/50 bg-gray-800/80 text-gray-400">
                <th className="px-3 py-2 text-left font-medium">Symbol</th>
                <th className="px-3 py-2 text-left font-medium">Name</th>
                <th className="px-3 py-2 text-left font-medium">Type</th>
                <th className="px-3 py-2 text-right font-medium">Current</th>
                <th className="px-3 py-2 text-right font-medium">Prev Close</th>
                <th className="px-3 py-2 text-right font-medium">Change</th>
                <th className="px-3 py-2 text-right font-medium">Change %</th>
                <th className="px-3 py-2 text-right font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {instruments.map((inst) => (
                <tr
                  key={inst.conId || inst.symbol}
                  className="border-b border-gray-800/50 transition-colors hover:bg-gray-800/40"
                >
                  <td className="px-3 py-2 font-mono font-medium text-white">
                    {inst.localSymbol || inst.symbol}
                  </td>
                  <td className="max-w-[180px] truncate px-3 py-2 text-xs text-gray-500">
                    {(inst as any).name || ''}
                  </td>
                  <td className="px-3 py-2 text-gray-400">{inst.secType}</td>
                  <td className={`px-3 py-2 text-right font-mono ${changeCls(inst.change)}`}>
                    {inst.current_price != null ? `$${fmt(inst.current_price)}` : '---'}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-gray-400">
                    {inst.prev_close != null ? `$${fmt(inst.prev_close)}` : '---'}
                  </td>
                  <td className={`px-3 py-2 text-right font-mono ${changeCls(inst.change)}`}>
                    {inst.change != null ? `${inst.change >= 0 ? '+' : ''}${fmt(inst.change)}` : '---'}
                  </td>
                  <td className={`px-3 py-2 text-right font-mono ${changeCls(inst.change_pct)}`}>
                    {inst.change_pct != null ? `${inst.change_pct >= 0 ? '+' : ''}${fmt(inst.change_pct)}%` : '---'}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button
                      onClick={() => handleRemove(inst)}
                      className="text-gray-600 hover:text-red-400"
                      title="Remove"
                    >
                      <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Add Modal */}
      {showAdd && watchlistId && (
        <AddInstrumentModal
          watchlistId={watchlistId}
          onClose={() => setShowAdd(false)}
          onAdded={() => { fetchInstruments(); onWatchlistsChanged() }}
        />
      )}
    </div>
  )
}
