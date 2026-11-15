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
  board: (date: string, signal?: AbortSignal) => fetchAPI<EtfBoardResponse>(`/etf/board${date ? `?date=${encodeURIComponent(date)}` : ''}`, { signal }),
  dates: (signal?: AbortSignal) => fetchAPI<string[]>('/etf/dates', { signal }),
  national: (date: string, signal?: AbortSignal) => fetchAPI<EtfNationalTeam>(`/etf/national-team${date ? `?date=${encodeURIComponent(date)}` : ''}`, { signal, timeoutMs: 50000 }),
}
