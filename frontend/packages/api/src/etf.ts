import { fetchAPI } from './client'

export interface EtfMinutePoint {
  minute: string
  turnover_cny: number | null
  etf_count: number
  index_close: number | null
}

export type EtfIntradayIssue = 'key_required' | 'permission_required' | 'rate_limited' | 'source_disabled' | 'unavailable'

export interface EtfMarketClock {
  at: string
  date: string
  timezone: string
  trading_day: boolean
  next_trading_day: string | null
}

export interface EtfIntraday {
  source: 'tushare'
  date: string
  today: string
  market: EtfMarketClock
  latest: string
  previous: string | null
  next: string | null
  status: 'live' | 'archive' | 'waiting' | 'closed'
  cached: boolean
  archived: boolean
  issues: EtfIntradayIssue[]
  previous_close: number | null
  previous_close_date: string | null
  etf_count: number
  symbols: string[]
  names: Record<string, string>
  broad_count: number | null
  disclosures: Record<string, { report_date: string; url: string }>
  points: EtfMinutePoint[]
  turnover_baseline: EtfTurnoverBaselineState
}

export interface EtfTurnoverBaseline {
  sessions: number
  cumulative_cny: Record<string, number>
}

export type EtfTurnoverBaselineState =
  | { status: 'ready'; value: EtfTurnoverBaseline }
  | { status: 'needs_calculation' | 'unavailable' }

export interface EtfMarketStats {
  date: string
  breadth: {
    through: string | null
    points: Record<string, { up: number; down: number; flat: number; source?: 'backfill' }>
    preview?: { through: string; total: number; minimum: number; minutes: Record<string, number> }
  }
  daily_flow: {
    status: 'ready' | 'partial' | 'pending' | 'unavailable'
    total: number
    covered: number
    net_cny: number | null
  }
  backfill?: EtfBreadthBackfill | null
}

export interface EtfBreadthBackfill {
  status: 'running' | 'complete' | 'partial' | 'failed'
  processed: number
  total: number
  added: number
  through?: string
  reason: EtfIntradayIssue | 'missing_minutes' | 'missing_stocks' | null
}

export type EtfBreadthBackfillStart = 'running' | 'busy' | 'cooldown' | 'nothing_to_fill' | 'unavailable'

export type PriceInstrumentKind = 'etf' | 'index'

export interface EtfPriceInstrument {
  symbol: string
  name: string
  kind?: PriceInstrumentKind
}

export interface EtfPriceLine {
  date: string
  symbol: string
  kind?: PriceInstrumentKind
  closes: Record<string, number>
  complete: boolean
  issue: EtfIntradayIssue | 'unknown_etf' | 'unknown_index' | null
}

export type EtfGroupId = 'csi300' | 'sse50' | 'csi500' | 'csi1000' | 'growth' | 'star' | 'a500' | 'sse'
export type EtfBoard = 'all' | 'main' | 'growth' | 'star' | 'beijing'
export interface EtfDistribution { up: number; down: number; flat: number; total: number; median: number | null; source?: string }
export interface EtfLinkedAnalysis {
  date: string
  groups: { id: EtfGroupId; index: string; symbols: string[]; points: Record<string, number | null>; baseline: Record<string, number> | null }[]
  benchmarks: { group: EtfGroupId; symbol: string; closes: Record<string, number>; previous_close: number | null; issue?: string | null }[]
  boards: Record<EtfBoard, Record<string, EtfDistribution>>
  backfill?: { status: string; processed: number; total: number; through: string; reason?: string } | null
}
export interface EtfComponents extends EtfDistribution {
  date: string; group: EtfGroupId; minute: string; covered: number; issue: string | null; weights_date?: string | null
  leaders: { symbol: string; name: string; change: number; contribution: number | null }[]
  laggards: { symbol: string; name: string; change: number; contribution: number | null }[]
  backfill?: { status: string; processed: number; total: number; through: string; reason?: string } | null
}

export const etfApi = {
  analysis(date: string, signal?: AbortSignal) {
    return fetchAPI<EtfLinkedAnalysis>(`/etf/analysis?${new URLSearchParams({ date })}`, { signal, timeoutMs: 90000 })
  },
  components(date: string, group: EtfGroupId, minute: string, signal?: AbortSignal) {
    return fetchAPI<EtfComponents>(`/etf/components?${new URLSearchParams({ date, group, minute })}`, { signal, timeoutMs: 45000 })
  },
  backfillComponents(date: string, group: EtfGroupId | 'all') {
    return fetchAPI<{ status: string; reason?: string }>(`/etf/components/backfill?${new URLSearchParams({ date, group })}`, { method: 'POST' })
  },
  priceCatalog(signal?: AbortSignal, kind: PriceInstrumentKind = 'etf') {
    return fetchAPI<{ items: EtfPriceInstrument[]; issue: EtfIntradayIssue | null }>(
      `/etf/price-catalog?${new URLSearchParams({ include_all: 'true', kind })}`, { signal },
    )
  },
  priceLine(date: string, symbol: string, signal?: AbortSignal, kind: PriceInstrumentKind = 'etf') {
    return fetchAPI<EtfPriceLine>(`/etf/price-line?${new URLSearchParams({ date, symbol, kind })}`, { signal, timeoutMs: 45000 })
  },
  intraday(date: string, refresh: boolean, signal?: AbortSignal) {
    const query = new URLSearchParams()
    if (date) query.set('date', date)
    if (refresh) query.set('refresh', 'true')
    return fetchAPI<EtfIntraday>(`/etf/intraday?${query}`, { signal, timeoutMs: 45000 })
  },
  turnoverBaseline(date: string, signal?: AbortSignal) {
    const query = new URLSearchParams({ date })
    return fetchAPI<EtfTurnoverBaseline | null>(`/etf/turnover-baseline?${query}`, { signal, timeoutMs: 90000 })
  },
  marketStats(date: string, signal?: AbortSignal) {
    const query = new URLSearchParams()
    if (date) query.set('date', date)
    return fetchAPI<EtfMarketStats>(`/etf/market-stats?${query}`, { signal })
  },
  backfillBreadth(date: string) {
    const query = new URLSearchParams({ date })
    return fetchAPI<{ date: string; status: EtfBreadthBackfillStart }>(`/etf/market-breadth/backfill?${query}`, { method: 'POST' })
  },
}
