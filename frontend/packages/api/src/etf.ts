import { fetchAPI } from './client'

export interface EtfWindow { start: string; end: string; amount: number; base: number | null; ratio: number | null; base_days: number; complete: boolean }
export interface EtfRow {
  code: string; name: string; index: string; manager: string; change_percent: number | null;
  amount: number | null; close: number | null; net: number | null; net20: number | null;
  shares_delta: number | null; scale: number | null; peak_window: EtfWindow | null;
}
export interface EtfDay { date: string; net: number | null; hs300: number | null; hs300_change_percent: number | null; covered: number; peak_window: EtfWindow | null }
export interface EtfBoard {
  date: string; status: string; amount: number | null; net: number | null; net20: number | null;
  covered: number; shares_published: boolean; shares_final: boolean; updated_at: string;
  etfs: EtfRow[]; minutes: [string, number][]; profile: [string, number][];
  cumulative: [string, number, number, number][]; windows: EtfWindow[]; series: EtfDay[]; surges: EtfDay[];
  hs300_change_percent: number | null; signal: { kind: string; title: string; detail: string };
}
export interface EtfBoardResponse { payload: EtfBoard; stale: boolean; snapshot_id: number; observed_at: string }
export interface EtfHolding {
  holder_name: string; institution: string; code: string; name: string; index: string; report_date: string;
  previous_report_date: string | null; shares: number; ratio_percent: number; shares_change: number | null;
  known_from: string; announced_at: string | null; source_url: string; snapshot_id: number;
}
export interface EtfSignal { date: string; kind: string; actor: null; net_subscription_estimate_cny: number; peak_ratio: number; index_change_percent: number; covered: number }
export interface EtfNationalTeam {
  date: string; holdings: EtfHolding[]; institutions: string[]; holding_etf_count: number;
  watchlist: (EtfRow & { disclosed_ratio: number })[]; watchlist_net_estimate_cny: number | null;
  signals: EtfSignal[]; coverage: { code: string; report_date: string | null }[]; stale: boolean;
}
export const etfApi = {
  history: (query: EtfHistoryQuery, signal?: AbortSignal) => {
    const params = new URLSearchParams()
    Object.entries(query).forEach(([key, value]) => { if (value) params.set(key, value) })
    return fetchAPI<EtfHistory>(`/etf/history?${params}`, { signal, timeoutMs: 50000 })
  },
  board: (date: string, signal?: AbortSignal) => fetchAPI<EtfBoardResponse>(`/etf/board${date ? `?date=${encodeURIComponent(date)}` : ''}`, { signal }),
  dates: (signal?: AbortSignal) => fetchAPI<string[]>('/etf/dates', { signal }),
  national: (date: string, signal?: AbortSignal) => fetchAPI<EtfNationalTeam>(`/etf/national-team${date ? `?date=${encodeURIComponent(date)}` : ''}`, { signal, timeoutMs: 50000 }),
}

export type EtfPeriod = '1m' | '3m' | '6m' | '1y' | 'all' | 'custom'
export type EtfBenchmarkCode = '000001' | '000300' | '000688'
export interface EtfBenchmarkPoint { close: number; return_percent: number | null; snapshot_id: number }
export interface EtfHistoryPoint {
  date: string; net: number | null; amount: number | null; scale: number | null; cumulative_net: number | null;
  hs300: number | null; hs300_change_percent: number | null; peak_ratio: number | null;
  covered: number; expected: number; snapshot_ids: number[];
  cumulative_net_days: number;
  benchmarks?: Partial<Record<EtfBenchmarkCode, EtfBenchmarkPoint>>;
}
export interface EtfHoldingPoint {
  date: string; shares: number | null; reported_shares: number | null; held_funds: number;
  reported_funds: number; expected_funds: number; before_range: boolean; snapshot_ids: number[];
}
export interface EtfHistory {
  benchmark_base_date?: string | null;
  range: { start: string; end: string }; period: EtfPeriod; scope: 'market' | 'national';
  available_start: string | null; available_end: string | null; collecting: boolean; stale: boolean;
  series: EtfHistoryPoint[]; holdings_trend: EtfHoldingPoint[]; disclosures: EtfHolding[];
  universe: { code: string; name: string }[];
  summary: { net: number | null; inflow: number | null; outflow: number | null; amount: number | null;
    days: number; net_days: number; amount_days: number; loaded_days: number; funds: number; coverage_min: number; coverage_max: number;
    aggregation: 'available_observations'; missing_net_dates: string[]; missing_amount_dates: string[] };
  funds: { code: string; name: string; index: string; net: number | null; amount: number | null;
    scale: number | null; as_of: string | null; days: number; amount_days: number; expected_days: number }[];
  signals: { date: string; net: number; peak_ratio: number; hs300_change_percent: number }[];
  flow_attribution: 'all_etf_investors'; composition_mode: 'period_end_disclosed' | 'broad_market';
}
export interface EtfHistoryQuery {
  period: EtfPeriod; scope: 'market' | 'national'; start?: string; end?: string; code?: string; institution?: string;
}
