import { useState, useEffect, useCallback } from 'react'
import { Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import { useWebSocket } from './hooks/useWebSocket'
import { useAuth, useAuthProvider, AuthContext } from './hooks/useAuth'
import { authFetch } from './config'
import { ConnectionStatus } from './components/ConnectionStatus'
import { AccountSidebar } from './components/AccountSidebar'
import { AccountPage } from './components/AccountPage'
import { WatchlistPage } from './components/WatchlistPage'
import { LoginPage } from './components/LoginPage'
import type { WatchlistSummary } from './types'

function Dashboard() {
  const { connected, multiPortfolio, headlines, status, liveMode, toggleLive } = useWebSocket()
  const { username, logout } = useAuth()
  const [watchlists, setWatchlists] = useState<WatchlistSummary[]>([])
  const navigate = useNavigate()

  const fetchWatchlists = useCallback(async () => {
    try {
      const res = await authFetch('/api/watchlists')
      if (res.status === 401) return
      const data = await res.json()
      setWatchlists(data.watchlists || [])
    } catch {
      // ignore
    }
  }, [])

  useEffect(() => {
    fetchWatchlists()
  }, [fetchWatchlists])

  const handleCreateWatchlist = async () => {
    try {
      const res = await authFetch('/api/watchlists', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: 'New Watchlist' }),
      })
      const data = await res.json()
      await fetchWatchlists()
      navigate(`/watchlist/${data.id}`)
    } catch {
      // ignore
    }
  }

  const firstAccount = multiPortfolio.accounts[0]

  return (
    <div className="flex h-screen flex-col bg-gray-950 text-gray-100">
      {/* Header */}
      <header className="shrink-0 border-b border-gray-800 bg-gray-900/80 px-6 py-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <h1 className="text-lg font-bold tracking-tight">
              IBKR Dashboard
            </h1>
            <button
              onClick={toggleLive}
              className={`rounded-md px-3 py-1 text-xs font-bold uppercase tracking-wide transition-colors ${
                liveMode
                  ? 'bg-red-500/20 text-red-400 border border-red-500/40 hover:bg-red-500/30'
                  : 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 hover:bg-emerald-500/30'
              }`}
            >
              {liveMode
                ? connected ? 'Stop Live (~1s)' : 'Connecting...'
                : 'Start Live (~1s)'}
            </button>
            {liveMode && connected && (
              <span className="inline-flex items-center gap-1 text-xs text-red-400">
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-red-400 animate-pulse" />
                LIVE
              </span>
            )}
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs text-gray-500">{username}</span>
            <button
              onClick={logout}
              className="rounded-md px-2 py-1 text-xs text-gray-500 hover:bg-gray-800 hover:text-gray-300"
            >
              Logout
            </button>
            <ConnectionStatus
              connected={connected}
              lastUpdate={status?.last_update || null}
            />
          </div>
        </div>
      </header>

      {/* Body: Sidebar + Content */}
      <div className="flex flex-1 overflow-hidden">
        <AccountSidebar
          multiPortfolio={multiPortfolio}
          watchlists={watchlists}
          onCreateWatchlist={handleCreateWatchlist}
        />

        <Routes>
          <Route
            path="/account/:accountId"
            element={
              <AccountPage
                multiPortfolio={multiPortfolio}
                headlines={headlines}
                liveMode={liveMode}
              />
            }
          />
          <Route
            path="/watchlist/:watchlistId"
            element={
              <WatchlistPage
                liveMode={liveMode}
                onWatchlistsChanged={fetchWatchlists}
              />
            }
          />
          <Route
            path="*"
            element={
              firstAccount
                ? <Navigate to={`/account/${firstAccount}`} replace />
                : <div className="flex flex-1 items-center justify-center text-gray-600">
                    Waiting for account data...
                  </div>
            }
          />
        </Routes>
      </div>
    </div>
  )
}

export default function App() {
  const auth = useAuthProvider()

  return (
    <AuthContext.Provider value={auth}>
      {auth.loading ? (
        <div className="flex h-screen items-center justify-center bg-gray-950">
          <div className="text-gray-500">Loading...</div>
        </div>
      ) : auth.isAuthenticated ? (
        <Dashboard />
      ) : (
        <LoginPage />
      )}
    </AuthContext.Provider>
  )
}
