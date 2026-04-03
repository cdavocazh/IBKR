/** Base path for API and WebSocket requests, derived from Vite's base config */
const base = import.meta.env.BASE_URL.replace(/\/$/, '')
export const API = (path: string) => `${base}${path}`
export const WS_URL = () => {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${protocol}://${window.location.host}${base}/ws`
}

/** Create fetch init with auth header */
export function authHeaders(): Record<string, string> {
  const token = localStorage.getItem('ibkr_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/** Authenticated fetch helper */
export async function authFetch(path: string, init?: RequestInit): Promise<Response> {
  const headers = { ...authHeaders(), ...(init?.headers as Record<string, string> || {}) }
  return fetch(API(path), { ...init, headers })
}
