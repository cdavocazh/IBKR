import { useState, useEffect, useRef, useCallback } from 'react'
import type { MultiAccountPortfolio, NewsHeadline, StatusData, WSMessage } from '../types'
import { WS_URL } from '../config'

const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 15000, 30000]

export function useWebSocket() {
  const [connected, setConnected] = useState(false)
  const [multiPortfolio, setMultiPortfolio] = useState<MultiAccountPortfolio>({
    accounts: [],
    portfolios: {},
    orders: {},
  })
  const [headlines, setHeadlines] = useState<NewsHeadline[]>([])
  const [status, setStatus] = useState<StatusData | null>(null)
  const [liveMode, setLiveMode] = useState(false)

  const wsRef = useRef<WebSocket | null>(null)
  const retryCount = useRef(0)
  const retryTimer = useRef<ReturnType<typeof setTimeout>>(undefined)

  const toggleLive = useCallback(() => {
    const newState = !liveMode
    setLiveMode(newState)
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'toggle_live', enabled: newState }))
    }
  }, [liveMode])

  const connect = useCallback(() => {
    const ws = new WebSocket(WS_URL())
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      retryCount.current = 0

      const ping = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send('ping')
      }, 30000)
      ws.addEventListener('close', () => clearInterval(ping))
    }

    ws.onmessage = (event) => {
      try {
        const msg: WSMessage = JSON.parse(event.data)

        if (msg.type === 'portfolio') {
          // Multi-account format: { accounts: [...], portfolios: { acctId: { summary, positions } } }
          const data = msg.data as MultiAccountPortfolio
          if (data.accounts && data.portfolios) {
            setMultiPortfolio(data)
          }
        } else if (msg.type === 'news') {
          setHeadlines((prev) => [msg.data, ...prev].slice(0, 200))
        } else if (msg.type === 'news_batch') {
          setHeadlines((prev) => {
            const existing = new Set(prev.map((h) => h.articleId))
            const newItems = (msg.data as NewsHeadline[]).filter(
              (h) => !existing.has(h.articleId)
            )
            return [...newItems, ...prev].slice(0, 200)
          })
        } else if (msg.type === 'status') {
          setStatus(msg.data)
          if (msg.data.live_mode !== undefined) {
            setLiveMode(msg.data.live_mode)
          }
        } else if (msg.type === 'live_mode') {
          setLiveMode(msg.data.enabled)
        }
      } catch {
        // ignore parse errors
      }
    }

    ws.onclose = () => {
      setConnected(false)
      wsRef.current = null
      const delay = RECONNECT_DELAYS[Math.min(retryCount.current, RECONNECT_DELAYS.length - 1)]
      retryCount.current += 1
      retryTimer.current = setTimeout(connect, delay)
    }

    ws.onerror = () => ws.close()
  }, [])

  useEffect(() => {
    connect()
    return () => {
      if (retryTimer.current) clearTimeout(retryTimer.current)
      if (wsRef.current) wsRef.current.close()
    }
  }, [connect])

  return { connected, multiPortfolio, headlines, status, liveMode, toggleLive }
}
