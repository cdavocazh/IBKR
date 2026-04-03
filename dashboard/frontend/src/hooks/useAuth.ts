import { useState, useEffect, useCallback, createContext, useContext } from 'react'
import { API } from '../config'

interface AuthState {
  token: string | null
  username: string | null
  isAuthenticated: boolean
  loading: boolean
  login: (username: string, password: string) => Promise<string | null>
  register: (username: string, password: string) => Promise<string | null>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}

export { AuthContext }

export function useAuthProvider(): AuthState {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('ibkr_token'))
  const [username, setUsername] = useState<string | null>(() => localStorage.getItem('ibkr_username'))
  const [loading, setLoading] = useState(true)

  // Validate existing token on mount
  useEffect(() => {
    if (!token) {
      setLoading(false)
      return
    }
    fetch(API('/api/auth/me'), {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => {
        if (!res.ok) {
          localStorage.removeItem('ibkr_token')
          localStorage.removeItem('ibkr_username')
          setToken(null)
          setUsername(null)
        }
      })
      .catch(() => {
        // Server not reachable — keep token, will retry
      })
      .finally(() => setLoading(false))
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const login = useCallback(async (u: string, p: string): Promise<string | null> => {
    try {
      const res = await fetch(API('/api/auth/login'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: u, password: p }),
      })
      if (!res.ok) {
        const data = await res.json()
        return data.detail || 'Login failed'
      }
      const data = await res.json()
      localStorage.setItem('ibkr_token', data.token)
      localStorage.setItem('ibkr_username', data.username)
      setToken(data.token)
      setUsername(data.username)
      return null
    } catch {
      return 'Connection error'
    }
  }, [])

  const register = useCallback(async (u: string, p: string): Promise<string | null> => {
    try {
      const res = await fetch(API('/api/auth/register'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: u, password: p }),
      })
      if (!res.ok) {
        const data = await res.json()
        return data.detail || 'Registration failed'
      }
      const data = await res.json()
      localStorage.setItem('ibkr_token', data.token)
      localStorage.setItem('ibkr_username', data.username)
      setToken(data.token)
      setUsername(data.username)
      return null
    } catch {
      return 'Connection error'
    }
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem('ibkr_token')
    localStorage.removeItem('ibkr_username')
    setToken(null)
    setUsername(null)
  }, [])

  return {
    token,
    username,
    isAuthenticated: !!token,
    loading,
    login,
    register,
    logout,
  }
}
