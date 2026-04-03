export interface Position {
  symbol: string
  local_symbol: string
  sec_type: string
  exchange: string
  currency: string
  position_size: number
  avg_cost: number
  multiplier: number
  current_price: number | null
  prev_close: number | null
  market_price: number | null
  market_value: number | null
  unrealized_pnl: number | null
  realized_pnl: number | null
  pnl_pct: number | null
  account: string
  con_id: number
  mark_price: number | null
  futures_oi: number | null
  daily_pnl: number | null
  strike: number | null
  right: string | null
  expiry: string | null
}

export interface ChartBar {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface PortfolioSummary {
  total_market_value: number
  total_unrealized_pnl: number
  total_realized_pnl: number
  total_pnl_pct: number | null
  position_count: number
  net_liquidation: number | null
  available_funds: number | null
  maint_margin_req: number | null
  last_update: string | null
}

export interface NewsHeadline {
  headline: string
  provider: string
  time: string
  articleId: string
  metadata: {
    confidence?: number
    keywords?: string
  }
}

export interface WSMessage {
  type: 'portfolio' | 'news' | 'news_batch' | 'status' | 'live_mode'
  data: any
}

export interface PortfolioData {
  summary: PortfolioSummary
  positions: Position[]
}

export interface Order {
  symbol: string
  local_symbol: string
  sec_type: string
  action: string
  order_type: string
  total_qty: number
  limit_price: number | null
  aux_price: number | null
  status: string
  filled: number
  remaining: number
  avg_fill_price: number | null
  order_id: number
  perm_id: number
  tif: string
}

export interface WatchlistSummary {
  id: string
  name: string
  count: number
}

export interface WatchlistInstrument {
  conId: number
  symbol: string
  localSymbol: string
  secType: string
  exchange: string
  currency: string
  current_price?: number | null
  prev_close?: number | null
  change?: number | null
  change_pct?: number | null
}

export interface SearchResult {
  conId: number | null
  symbol: string
  localSymbol: string
  name?: string
  secType: string
  exchange: string
  currency: string
  source?: 'yahoo' | 'ibkr'
}

export interface InstrumentDetails {
  conId: number
  symbol: string
  localSymbol: string
  secType: string
  exchange: string
  currency: string
  longName: string
  category: string
  subcategory: string
  multiplier: string
  minTick: number
  lastTradeDate: string
  tradingHours: string
  relatedContracts: RelatedContract[]
}

export interface RelatedContract {
  conId: number
  symbol: string
  localSymbol: string
  lastTradeDate: string
  multiplier: string
  exchange: string
  currency: string
  name: string
  openInterest: number | null
}

/** Multi-account portfolio data from WebSocket */
export interface MultiAccountPortfolio {
  accounts: string[]
  portfolios: Record<string, PortfolioData>
  orders: Record<string, Order[]>
}

export interface StatusData {
  connected: boolean
  position_count: number
  account_count: number
  last_update: string | null
  live_mode: boolean
  library: string
}
