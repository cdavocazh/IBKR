import { useEffect, useRef, useState, useCallback } from 'react'
import { createChart, type IChartApi, CandlestickSeries, ColorType } from 'lightweight-charts'
import type { Position, ChartBar } from '../types'
import { API } from '../config'

const BAR_SIZES = ['1min', '5min', '15min', '1hour', '1day', '1week'] as const
type BarSize = (typeof BAR_SIZES)[number]

const BAR_SIZE_LABELS: Record<BarSize, string> = {
  '1min': '1m',
  '5min': '5m',
  '15min': '15m',
  '1hour': '1H',
  '1day': '1D',
  '1week': '1W',
}

// Refresh intervals by bar size (ms)
const REFRESH_INTERVALS: Record<BarSize, number> = {
  '1min': 5000,
  '5min': 10000,
  '15min': 30000,
  '1hour': 60000,
  '1day': 300000,
  '1week': 300000,
}

interface Props {
  position: Position
  onClose: () => void
  liveMode?: boolean
}

export function PriceChart({ position, onClose, liveMode }: Props) {
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const seriesRef = useRef<any>(null)
  const barsRef = useRef<ChartBar[]>([])
  const [barSize, setBarSize] = useState<BarSize>('1hour')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [autoRefresh, setAutoRefresh] = useState(true)

  const fetchBars = useCallback(async (size: BarSize, isRefresh = false) => {
    if (!isRefresh) {
      setLoading(true)
      setError(null)
    }
    try {
      const res = await fetch(API(`/api/chart?conId=${position.con_id}&barSize=${size}`))
      const data = await res.json()
      if (data.error) {
        if (!isRefresh) setError(data.error)
        return
      }
      const bars: ChartBar[] = data.bars || []
      if (bars.length === 0) {
        if (!isRefresh) setError('No data available')
        return
      }

      barsRef.current = bars

      if (seriesRef.current && chartRef.current) {
        if (isRefresh && bars.length > 0) {
          // Only update the last few bars (new + current incomplete bar)
          const lastBars = bars.slice(-3)
          for (const b of lastBars) {
            seriesRef.current.update({
              time: b.time as any,
              open: b.open,
              high: b.high,
              low: b.low,
              close: b.close,
            })
          }
        } else {
          seriesRef.current.setData(
            bars.map((b) => ({
              time: b.time as any,
              open: b.open,
              high: b.high,
              low: b.low,
              close: b.close,
            }))
          )
          chartRef.current.timeScale().fitContent()
        }
      }
    } catch {
      if (!isRefresh) setError('Failed to fetch chart data')
    } finally {
      if (!isRefresh) setLoading(false)
    }
  }, [position.con_id])

  // Create chart on mount
  useEffect(() => {
    if (!chartContainerRef.current) return

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#111827' },
        textColor: '#9ca3af',
      },
      grid: {
        vertLines: { color: '#1f2937' },
        horzLines: { color: '#1f2937' },
      },
      crosshair: {
        vertLine: { color: '#4b5563', width: 1, style: 3 },
        horzLine: { color: '#4b5563', width: 1, style: 3 },
      },
      timeScale: {
        borderColor: '#374151',
        timeVisible: true,
        secondsVisible: false,
      },
      rightPriceScale: {
        borderColor: '#374151',
      },
      width: chartContainerRef.current.clientWidth,
      height: 420,
    })

    const series = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981',
      downColor: '#ef4444',
      borderUpColor: '#10b981',
      borderDownColor: '#ef4444',
      wickUpColor: '#10b981',
      wickDownColor: '#ef4444',
    })

    chartRef.current = chart
    seriesRef.current = series

    // Resize handler
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        chart.applyOptions({ width: entry.contentRect.width })
      }
    })
    ro.observe(chartContainerRef.current)

    return () => {
      ro.disconnect()
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
    }
  }, [])

  // Fetch data when barSize changes
  useEffect(() => {
    if (chartRef.current) {
      fetchBars(barSize)
    }
  }, [barSize, fetchBars])

  // Auto-refresh for live updates
  useEffect(() => {
    if (!autoRefresh || !liveMode) return

    const interval = setInterval(() => {
      fetchBars(barSize, true)
    }, REFRESH_INTERVALS[barSize])

    return () => clearInterval(interval)
  }, [autoRefresh, liveMode, barSize, fetchBars])

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  const pnlColor = position.pnl_pct != null
    ? position.pnl_pct >= 0 ? 'text-emerald-400' : 'text-red-400'
    : 'text-gray-400'

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="w-full max-w-4xl rounded-xl border border-gray-700 bg-gray-900 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-700 px-5 py-3">
          <div className="flex items-center gap-4">
            <h3 className="text-lg font-bold font-mono text-white">
              {position.local_symbol}
            </h3>
            <span className="text-sm text-gray-400">{position.sec_type}</span>
            {position.current_price != null && (
              <span className="text-lg font-mono text-white">
                ${position.current_price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
            )}
            {position.pnl_pct != null && (
              <span className={`text-sm font-mono ${pnlColor}`}>
                {position.pnl_pct >= 0 ? '+' : ''}{position.pnl_pct.toFixed(2)}%
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {liveMode && (
              <button
                onClick={() => setAutoRefresh((v) => !v)}
                className={`rounded px-2 py-1 text-xs font-medium transition-colors ${
                  autoRefresh
                    ? 'bg-emerald-600/20 text-emerald-400 border border-emerald-500/30'
                    : 'bg-gray-800 text-gray-500 border border-gray-700'
                }`}
                title={autoRefresh ? 'Auto-refresh ON' : 'Auto-refresh OFF'}
              >
                {autoRefresh ? 'LIVE' : 'PAUSED'}
              </button>
            )}
            <button
              onClick={onClose}
              className="rounded-md p-1.5 text-gray-400 hover:bg-gray-800 hover:text-white"
            >
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Granularity selector */}
        <div className="flex gap-1 border-b border-gray-800 px-5 py-2">
          {BAR_SIZES.map((size) => (
            <button
              key={size}
              onClick={() => setBarSize(size)}
              className={`rounded px-3 py-1 text-xs font-bold tracking-wide transition-colors ${
                barSize === size
                  ? 'bg-blue-600 text-white'
                  : 'text-gray-400 hover:bg-gray-800 hover:text-white'
              }`}
            >
              {BAR_SIZE_LABELS[size]}
            </button>
          ))}
        </div>

        {/* Chart */}
        <div className="relative px-2 py-2">
          {loading && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-gray-900/80">
              <span className="text-sm text-gray-400">Loading...</span>
            </div>
          )}
          {error && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-gray-900/80">
              <span className="text-sm text-red-400">{error}</span>
            </div>
          )}
          <div ref={chartContainerRef} />
        </div>
      </div>
    </div>
  )
}
