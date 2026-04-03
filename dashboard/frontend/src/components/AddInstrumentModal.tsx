import { useState, useRef, useEffect } from 'react'
import type { SearchResult, InstrumentDetails, RelatedContract } from '../types'
import { API, authFetch } from '../config'

interface Props {
  watchlistId: string
  onClose: () => void
  onAdded: () => void
}

export function AddInstrumentModal({ watchlistId, onClose, onAdded }: Props) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [searching, setSearching] = useState(false)
  const [adding, setAdding] = useState<string | null>(null)
  const [expandedConId, setExpandedConId] = useState<number | null>(null)
  const [details, setDetails] = useState<InstrumentDetails | null>(null)
  const [loadingDetails, setLoadingDetails] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [])

  const search = (q: string) => {
    setQuery(q)
    setExpandedConId(null)
    setDetails(null)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (q.length < 1) {
      setResults([])
      return
    }
    setSearching(true)
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await fetch(API(`/api/search?q=${encodeURIComponent(q)}`))
        const data = await res.json()
        setResults(data.results || [])
      } catch {
        setResults([])
      } finally {
        setSearching(false)
      }
    }, 400)
  }

  const addInstrument = async (r: SearchResult) => {
    const key = r.conId?.toString() || r.symbol
    setAdding(key)
    try {
      await authFetch(`/api/watchlists/${watchlistId}/instruments`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(r),
      })
      onAdded()
    } catch {
      // ignore
    } finally {
      setAdding(null)
    }
  }

  const addRelatedContract = (rc: RelatedContract) => {
    const sr: SearchResult = {
      conId: rc.conId,
      symbol: rc.symbol,
      localSymbol: rc.localSymbol,
      name: rc.name,
      secType: 'FUT',
      exchange: rc.exchange,
      currency: rc.currency,
      source: 'ibkr',
    }
    addInstrument(sr)
  }

  const toggleDetails = async (r: SearchResult) => {
    if (!r.conId || r.source !== 'ibkr') return
    if (expandedConId === r.conId) {
      setExpandedConId(null)
      setDetails(null)
      return
    }
    setExpandedConId(r.conId)
    setDetails(null)
    setLoadingDetails(true)
    try {
      const res = await authFetch(`/api/instrument-details?conId=${r.conId}`)
      const data = await res.json()
      if (!data.error) setDetails(data)
    } catch {
      // ignore
    } finally {
      setLoadingDetails(false)
    }
  }

  const fmtDate = (d: string) => {
    if (!d || d.length < 8) return d
    return `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}`
  }

  const fmtOI = (oi: number | null) => {
    if (oi == null) return '---'
    return oi.toLocaleString()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-2xl rounded-xl border border-gray-700 bg-gray-900 shadow-2xl">
        <div className="flex items-center justify-between border-b border-gray-700 px-4 py-3">
          <h3 className="text-sm font-medium text-white">Add Instrument</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-white">
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="p-4">
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => search(e.target.value)}
            placeholder="Search symbol (e.g. AAPL, NVDA, TSLA, ES)..."
            className="w-full rounded-lg border border-gray-600 bg-gray-800 px-4 py-2.5 text-sm text-white placeholder-gray-500 outline-none focus:border-blue-500"
          />
        </div>

        <div className="max-h-[28rem] overflow-y-auto px-4 pb-4">
          {searching && (
            <div className="py-4 text-center text-sm text-gray-500">Searching...</div>
          )}
          {!searching && query.length > 0 && results.length === 0 && (
            <div className="py-4 text-center text-sm text-gray-500">No results</div>
          )}
          {results.map((r) => {
            const key = r.conId?.toString() || r.symbol
            const isExpanded = expandedConId === r.conId
            const isExpandable = r.conId != null && r.source === 'ibkr'
            return (
              <div key={key}>
                <div
                  onClick={() => isExpandable && toggleDetails(r)}
                  className={`flex items-center justify-between rounded-lg px-3 py-2 ${
                    isExpandable ? 'cursor-pointer' : ''
                  } ${isExpanded ? 'bg-gray-800' : 'hover:bg-gray-800'}`}
                >
                  <div className="flex items-center gap-2 overflow-hidden">
                    {isExpandable && (
                      <svg
                        className={`h-3 w-3 shrink-0 text-gray-500 transition-transform ${isExpanded ? 'rotate-90' : ''}`}
                        fill="none" viewBox="0 0 24 24" stroke="currentColor"
                      >
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                      </svg>
                    )}
                    <span className="font-mono text-sm font-medium text-white">{r.symbol}</span>
                    <span className="rounded bg-gray-700 px-1.5 py-0.5 text-xs text-gray-400">{r.secType}</span>
                    {r.name && (
                      <span className="truncate text-xs text-gray-500">{r.name}</span>
                    )}
                    <span className="text-xs text-gray-600">{r.exchange}</span>
                    <span className={`shrink-0 rounded px-1 py-0.5 text-[10px] font-medium ${
                      r.source === 'ibkr'
                        ? 'bg-emerald-500/20 text-emerald-400'
                        : 'bg-purple-500/20 text-purple-400'
                    }`}>
                      {r.source === 'ibkr' ? 'IBKR' : 'Yahoo'}
                    </span>
                  </div>
                  <button
                    onClick={(e) => { e.stopPropagation(); addInstrument(r) }}
                    disabled={adding === key}
                    className="ml-2 shrink-0 rounded-md bg-blue-600 px-3 py-1 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-50"
                  >
                    {adding === key ? '...' : 'Add'}
                  </button>
                </div>

                {/* Expanded detail panel */}
                {isExpanded && (
                  <div className="mb-2 ml-5 rounded-lg border border-gray-700/50 bg-gray-800/50 p-3">
                    {loadingDetails && (
                      <div className="py-3 text-center text-xs text-gray-500">Loading details...</div>
                    )}
                    {details && !loadingDetails && (
                      <div className="space-y-3">
                        {/* Contract info */}
                        <div>
                          <div className="mb-1.5 text-xs font-medium text-gray-400">Contract Details</div>
                          <div className="grid grid-cols-3 gap-x-4 gap-y-1 text-xs">
                            <div>
                              <span className="text-gray-500">Name: </span>
                              <span className="text-gray-300">{details.longName || '---'}</span>
                            </div>
                            <div>
                              <span className="text-gray-500">Exchange: </span>
                              <span className="text-gray-300">{details.exchange}</span>
                            </div>
                            <div>
                              <span className="text-gray-500">Currency: </span>
                              <span className="text-gray-300">{details.currency}</span>
                            </div>
                            {details.multiplier && (
                              <div>
                                <span className="text-gray-500">Multiplier: </span>
                                <span className="text-gray-300">{details.multiplier}</span>
                              </div>
                            )}
                            {details.minTick > 0 && (
                              <div>
                                <span className="text-gray-500">Min Tick: </span>
                                <span className="text-gray-300">{details.minTick}</span>
                              </div>
                            )}
                            {details.category && (
                              <div>
                                <span className="text-gray-500">Category: </span>
                                <span className="text-gray-300">{details.category}</span>
                              </div>
                            )}
                            {details.lastTradeDate && (
                              <div>
                                <span className="text-gray-500">Expiry: </span>
                                <span className="text-gray-300">{fmtDate(details.lastTradeDate)}</span>
                              </div>
                            )}
                          </div>
                        </div>

                        {/* Delivery months for futures */}
                        {details.relatedContracts.length > 0 && (
                          <div>
                            <div className="mb-1.5 text-xs font-medium text-gray-400">
                              Delivery Months ({details.relatedContracts.length})
                            </div>
                            <div className="overflow-hidden rounded border border-gray-700/50">
                              <table className="w-full text-xs">
                                <thead>
                                  <tr className="border-b border-gray-700/50 bg-gray-800 text-gray-500">
                                    <th className="px-2 py-1.5 text-left font-medium">Contract</th>
                                    <th className="px-2 py-1.5 text-left font-medium">Expiry</th>
                                    <th className="px-2 py-1.5 text-right font-medium">Open Interest</th>
                                    <th className="px-2 py-1.5 text-right font-medium"></th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {details.relatedContracts.map((rc) => (
                                    <tr
                                      key={rc.conId}
                                      className="border-b border-gray-800/50 transition-colors hover:bg-gray-800/40"
                                    >
                                      <td className="px-2 py-1.5 font-mono text-gray-300">
                                        {rc.localSymbol}
                                      </td>
                                      <td className="px-2 py-1.5 text-gray-400">
                                        {fmtDate(rc.lastTradeDate)}
                                      </td>
                                      <td className="px-2 py-1.5 text-right font-mono text-gray-400">
                                        {fmtOI(rc.openInterest)}
                                      </td>
                                      <td className="px-2 py-1.5 text-right">
                                        <button
                                          onClick={(e) => { e.stopPropagation(); addRelatedContract(rc) }}
                                          disabled={adding === rc.conId.toString()}
                                          className="rounded bg-blue-600/80 px-2 py-0.5 text-[10px] font-medium text-white hover:bg-blue-500 disabled:opacity-50"
                                        >
                                          {adding === rc.conId.toString() ? '...' : 'Add'}
                                        </button>
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
