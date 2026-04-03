import { useState } from 'react'
import type { NewsHeadline } from '../types'
import { API } from '../config'

const providerStyles: Record<string, string> = {
  BRFG: 'bg-blue-500/20 text-blue-300 border-blue-500/30',
  BRFUPDN: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
  DJNL: 'bg-orange-500/20 text-orange-300 border-orange-500/30',
  'DJ-N': 'bg-orange-500/20 text-orange-300 border-orange-500/30',
  'DJ-RT': 'bg-amber-500/20 text-amber-300 border-amber-500/30',
}

const defaultBadge = 'bg-gray-500/20 text-gray-300 border-gray-500/30'

function formatTime(timeStr: string): string {
  try {
    const d = new Date(timeStr)
    if (isNaN(d.getTime())) return timeStr.slice(0, 16)
    const now = new Date()
    const diff = (now.getTime() - d.getTime()) / 1000

    if (diff < 60) return 'just now'
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  } catch {
    return timeStr.slice(0, 16)
  }
}

function stripHtml(html: string): string {
  // Simple HTML to text conversion
  return html
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/p>/gi, '\n\n')
    .replace(/<[^>]+>/g, '')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

interface Props {
  headlines: NewsHeadline[]
}

export function NewsFeed({ headlines }: Props) {
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [articleText, setArticleText] = useState<string | null>(null)
  const [loadingArticle, setLoadingArticle] = useState(false)

  const toggleArticle = async (h: NewsHeadline) => {
    if (expandedId === h.articleId) {
      setExpandedId(null)
      setArticleText(null)
      return
    }
    setExpandedId(h.articleId)
    setArticleText(null)
    setLoadingArticle(true)
    try {
      const res = await fetch(
        API(`/api/news/article?articleId=${encodeURIComponent(h.articleId)}&provider=${encodeURIComponent(h.provider)}`)
      )
      const data = await res.json()
      if (data.error) {
        setArticleText(`[Error: ${data.error}]`)
      } else {
        const text = data.articleText || ''
        setArticleText(stripHtml(text))
      }
    } catch {
      setArticleText('[Failed to load article]')
    } finally {
      setLoadingArticle(false)
    }
  }

  return (
    <div className="flex h-full flex-col rounded-lg border border-gray-700/50 bg-gray-800/30">
      <div className="border-b border-gray-700/50 px-4 py-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-400">
          News Feed
          <span className="ml-2 text-xs font-normal text-gray-600">
            ({headlines.length} headlines)
          </span>
        </h2>
      </div>
      <div className="flex-1 overflow-y-auto" style={{ maxHeight: 'calc(100vh - 340px)' }}>
        {headlines.map((h, i) => {
          const isExpanded = expandedId === h.articleId
          return (
            <div
              key={`${h.articleId || i}-${h.time}`}
              className={`border-b border-gray-800/50 transition-colors ${
                isExpanded ? 'bg-gray-800/60' : 'hover:bg-gray-800/40'
              }`}
            >
              <div
                className="cursor-pointer px-4 py-3"
                onClick={() => h.articleId && toggleArticle(h)}
              >
                <div className="mb-1 flex items-center gap-2">
                  <span
                    className={`inline-block rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase ${
                      providerStyles[h.provider] || defaultBadge
                    }`}
                  >
                    {h.provider}
                  </span>
                  <span className="text-xs text-gray-500">{formatTime(h.time)}</span>
                  {h.metadata?.confidence != null && (
                    <span className="text-xs text-gray-600">
                      conf: {(h.metadata.confidence * 100).toFixed(0)}%
                    </span>
                  )}
                </div>
                <p className="text-sm leading-snug text-gray-200">{h.headline}</p>
              </div>

              {/* Expanded article */}
              {isExpanded && (
                <div className="border-t border-gray-700/30 px-4 py-3">
                  {loadingArticle && (
                    <div className="py-2 text-xs text-gray-500">Loading article...</div>
                  )}
                  {articleText && !loadingArticle && (
                    <pre className="max-h-60 overflow-y-auto whitespace-pre-wrap text-xs leading-relaxed text-gray-300 font-sans">
                      {articleText}
                    </pre>
                  )}
                </div>
              )}
            </div>
          )
        })}
        {headlines.length === 0 && (
          <div className="px-4 py-12 text-center text-gray-500">
            Waiting for headlines...
          </div>
        )}
      </div>
    </div>
  )
}
