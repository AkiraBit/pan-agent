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

export const etfApi = {
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
}
