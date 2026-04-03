import { useState, useEffect } from 'react'
import { API } from '../config'

interface SentimentData {
  timestamp: string
  headline_count: number
  es_trading_direction: {
    signal: string
    confidence: number
    unified_sentiment: number
    newsletter_sentiment: number
    nlp_sentiment_24h: number
    net_sentiment_72h: number
    net_sentiment_7d: number
    dominant_category: string
    key_themes: string[]
    context_themes: string[]
    context_trend: string
    context_levels: {
      smashlevel_pivot?: number
      vpoc_5d?: number
      vpoc_20d?: number
      support?: number[]
      resistance?: number[]
      ma200?: number
    }
    context_positioning: {
      jpm_z_score?: number
      naaim?: string
      pct_above_20d?: number
    }
    context_key_risks: string
    context_vix_tier: number
    cross_validated: boolean
    actionable_insights: string[]
  }
}

interface HistoryRow {
  timestamp: string
  signal: string
  confidence: number
  unified_sentiment: number
  newsletter_sentiment: number
  nlp_sentiment_24h: number
  headline_count: number
  context_trend: string
}

const signalColor: Record<string, string> = {
  BULLISH: 'text-emerald-400',
  BEARISH: 'text-red-400',
  SIDEWAYS: 'text-yellow-400',
  NEUTRAL: 'text-gray-400',
}

const signalBg: Record<string, string> = {
  BULLISH: 'bg-emerald-500/20 border-emerald-500/40',
  BEARISH: 'bg-red-500/20 border-red-500/40',
  SIDEWAYS: 'bg-yellow-500/20 border-yellow-500/40',
  NEUTRAL: 'bg-gray-500/20 border-gray-500/40',
}

function sentimentBar(value: number): string {
  if (value > 0.2) return 'bg-emerald-500'
  if (value > 0.05) return 'bg-emerald-700'
  if (value < -0.2) return 'bg-red-500'
  if (value < -0.05) return 'bg-red-700'
  return 'bg-gray-500'
}

function formatTime(ts: string): string {
  try {
    const d = new Date(ts)
    if (isNaN(d.getTime())) return ts
    const now = new Date()
    const diff = (now.getTime() - d.getTime()) / 1000

    if (diff < 60) return 'just now'
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch {
    return ts
  }
}

function formatDateTime(ts: string): string {
  try {
    const d = new Date(ts)
    if (isNaN(d.getTime())) return ts
    return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch {
    return ts
  }
}

export function SentimentPanel() {
  const [data, setData] = useState<SentimentData | null>(null)
  const [history, setHistory] = useState<HistoryRow[]>([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [sentRes, histRes] = await Promise.all([
          fetch(API('/api/sentiment')),
          fetch(API('/api/sentiment/history')),
        ])
        if (sentRes.ok) {
          const d = await sentRes.json()
          if (!d.error) setData(d)
        }
        if (histRes.ok) {
          const h = await histRes.json()
          setHistory(h.reverse()) // newest first
        }
      } catch {
        // ignore
      } finally {
        setLoading(false)
      }
    }
    fetchData()
    const interval = setInterval(fetchData, 120_000) // refresh every 2 min
    return () => clearInterval(interval)
  }, [])

  if (loading) {
    return (
      <div className="rounded-lg border border-gray-700/50 bg-gray-800/30 px-4 py-8 text-center text-gray-500">
        Loading sentiment data...
      </div>
    )
  }

  if (!data) {
    return (
      <div className="rounded-lg border border-gray-700/50 bg-gray-800/30 px-4 py-6 text-center text-gray-500">
        No sentiment data available. Run <code className="text-gray-400">python scripts/run_sentiment.py</code> first.
      </div>
    )
  }

  const dir = data.es_trading_direction
  const levels = dir.context_levels || {}

  return (
    <div className="flex flex-col rounded-lg border border-gray-700/50 bg-gray-800/30">
      {/* Header */}
      <div className="border-b border-gray-700/50 px-4 py-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-400">
            ES Sentiment
            <span className="ml-2 text-xs font-normal text-gray-600">
              ({data.headline_count} headlines)
            </span>
          </h2>
          <span className="text-xs text-gray-500">{formatTime(data.timestamp)}</span>
        </div>
      </div>

      {/* Signal Banner */}
      <div className={`mx-3 mt-3 rounded-lg border px-4 py-3 ${signalBg[dir.signal] || signalBg.NEUTRAL}`}>
        <div className="flex items-center justify-between">
          <div>
            <div className="text-xs uppercase tracking-wider text-gray-400">Trading Direction</div>
            <div className={`text-2xl font-bold ${signalColor[dir.signal] || 'text-gray-300'}`}>
              {dir.signal}
            </div>
          </div>
          <div className="text-right">
            <div className="text-xs text-gray-400">Confidence</div>
            <div className="text-xl font-mono text-gray-200">{(dir.confidence * 100).toFixed(0)}%</div>
          </div>
        </div>
        {dir.cross_validated && (
          <div className="mt-1 text-xs text-emerald-400">Cross-validated with newsletters</div>
        )}
      </div>

      {/* Sentiment Scores */}
      <div className="grid grid-cols-3 gap-2 px-3 py-3">
        <SentimentScore label="Unified" value={dir.unified_sentiment} />
        <SentimentScore label="Newsletter" value={dir.newsletter_sentiment} />
        <SentimentScore label="NLP 24h" value={dir.nlp_sentiment_24h} />
      </div>

      {/* Key Levels */}
      {(levels.smashlevel_pivot || levels.support?.length || levels.resistance?.length) && (
        <div className="border-t border-gray-700/30 px-4 py-2">
          <div className="text-xs uppercase tracking-wider text-gray-500 mb-1">Key Levels</div>
          <div className="grid grid-cols-3 gap-2 text-xs">
            {levels.smashlevel_pivot && (
              <div>
                <span className="text-gray-500">Pivot:</span>{' '}
                <span className="text-gray-200 font-mono">{levels.smashlevel_pivot}</span>
              </div>
            )}
            {levels.support?.length ? (
              <div>
                <span className="text-red-400">Sup:</span>{' '}
                <span className="text-gray-200 font-mono">{levels.support.join(', ')}</span>
              </div>
            ) : null}
            {levels.resistance?.length ? (
              <div>
                <span className="text-emerald-400">Res:</span>{' '}
                <span className="text-gray-200 font-mono">{levels.resistance.join(', ')}</span>
              </div>
            ) : null}
            {levels.vpoc_5d && (
              <div>
                <span className="text-gray-500">VPOC 5d:</span>{' '}
                <span className="text-gray-200 font-mono">{levels.vpoc_5d}</span>
              </div>
            )}
            {levels.vpoc_20d && (
              <div>
                <span className="text-gray-500">VPOC 20d:</span>{' '}
                <span className="text-gray-200 font-mono">{levels.vpoc_20d}</span>
              </div>
            )}
            {levels.ma200 && (
              <div>
                <span className="text-gray-500">MA200:</span>{' '}
                <span className="text-gray-200 font-mono">{levels.ma200}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Positioning */}
      {dir.context_positioning && (dir.context_positioning.jpm_z_score || dir.context_positioning.pct_above_20d != null) && (
        <div className="border-t border-gray-700/30 px-4 py-2">
          <div className="text-xs uppercase tracking-wider text-gray-500 mb-1">Positioning</div>
          <div className="flex flex-wrap gap-3 text-xs">
            {dir.context_positioning.jpm_z_score != null && (
              <div>
                <span className="text-gray-500">JPM z:</span>{' '}
                <span className={`font-mono ${dir.context_positioning.jpm_z_score < -1 ? 'text-red-400' : dir.context_positioning.jpm_z_score > 1 ? 'text-emerald-400' : 'text-gray-200'}`}>
                  {dir.context_positioning.jpm_z_score.toFixed(1)}
                </span>
              </div>
            )}
            {dir.context_positioning.pct_above_20d != null && (
              <div>
                <span className="text-gray-500">%&gt;20d MA:</span>{' '}
                <span className="text-gray-200 font-mono">{dir.context_positioning.pct_above_20d}%</span>
              </div>
            )}
            {dir.context_vix_tier != null && (
              <div>
                <span className="text-gray-500">VIX tier:</span>{' '}
                <span className={`font-mono ${dir.context_vix_tier >= 5 ? 'text-red-400' : dir.context_vix_tier >= 3 ? 'text-yellow-400' : 'text-emerald-400'}`}>
                  {dir.context_vix_tier}/7
                </span>
              </div>
            )}
          </div>
          {dir.context_positioning.naaim && (
            <div className="mt-1 text-xs text-gray-400 truncate">{dir.context_positioning.naaim}</div>
          )}
        </div>
      )}

      {/* Key Themes (collapsed by default) */}
      <div className="border-t border-gray-700/30">
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex w-full items-center justify-between px-4 py-2 text-xs text-gray-400 hover:text-gray-300 transition-colors"
        >
          <span className="uppercase tracking-wider">
            Themes &amp; Insights ({dir.key_themes?.length || 0} themes, {dir.actionable_insights?.length || 0} insights)
          </span>
          <span>{expanded ? '▲' : '▼'}</span>
        </button>

        {expanded && (
          <div className="px-4 pb-3 space-y-2">
            {dir.key_themes?.length > 0 && (
              <div>
                <div className="text-xs text-gray-500 mb-1">Key Themes</div>
                <div className="flex flex-wrap gap-1">
                  {dir.key_themes.map((t, i) => (
                    <span key={i} className="rounded bg-gray-700/50 px-2 py-0.5 text-xs text-gray-300">
                      {t}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {dir.context_themes?.length > 0 && (
              <div>
                <div className="text-xs text-gray-500 mb-1">Newsletter Context</div>
                <ul className="space-y-0.5">
                  {dir.context_themes.slice(0, 6).map((t, i) => (
                    <li key={i} className="text-xs text-gray-300 leading-snug">
                      {t}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {dir.actionable_insights?.length > 0 && (
              <div>
                <div className="text-xs text-gray-500 mb-1">Actionable Insights</div>
                <ul className="space-y-0.5">
                  {dir.actionable_insights.slice(0, 8).map((ins, i) => (
                    <li key={i} className="text-xs text-gray-300 leading-snug">
                      {ins}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {dir.context_key_risks && (
              <div>
                <div className="text-xs text-gray-500 mb-1">Key Risks</div>
                <div className="text-xs text-red-300/80 leading-snug whitespace-pre-line">
                  {dir.context_key_risks.slice(0, 500)}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* History */}
      {history.length > 1 && (
        <div className="border-t border-gray-700/30 px-4 py-2">
          <div className="text-xs uppercase tracking-wider text-gray-500 mb-2">Signal History</div>
          <div className="space-y-1">
            {history.slice(0, 8).map((row, i) => (
              <div key={i} className="flex items-center gap-2 text-xs">
                <span className="text-gray-500 w-28 shrink-0 font-mono">{formatDateTime(row.timestamp)}</span>
                <span className={`w-16 font-bold ${signalColor[row.signal] || 'text-gray-400'}`}>
                  {row.signal}
                </span>
                <div className="flex-1 h-1.5 rounded-full bg-gray-700 overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${sentimentBar(row.unified_sentiment as number)}`}
                    style={{ width: `${Math.min(100, Math.abs((row.unified_sentiment as number) * 100) + 10)}%` }}
                  />
                </div>
                <span className="w-12 text-right font-mono text-gray-400">
                  {(row.unified_sentiment as number) > 0 ? '+' : ''}{((row.unified_sentiment as number) * 100).toFixed(0)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function SentimentScore({ label, value }: { label: string; value: number }) {
  const color = value > 0.05 ? 'text-emerald-400' : value < -0.05 ? 'text-red-400' : 'text-gray-400'
  return (
    <div className="rounded-lg bg-gray-800/50 px-3 py-2 text-center">
      <div className="text-[10px] uppercase tracking-wider text-gray-500">{label}</div>
      <div className={`text-lg font-mono font-bold ${color}`}>
        {value > 0 ? '+' : ''}{(value * 100).toFixed(1)}%
      </div>
    </div>
  )
}
