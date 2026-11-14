import { fetchAPI } from '@panwatch/api'

export interface Provenance {
  sources?: { id: string; name: string; url: string }[]; method?: string
}
export interface ReviewResponse<T> extends Provenance {
  payload: T; source: string; source_url: string; fetched_at: string; stale: boolean; error: string | null
}
export interface MinutePoint { time: string; price: number; change_percent: number }
export interface LimitStock {
  code: string; name: string; trade_date?: string; price?: number | null; change_percent?: number | null;
  active?: boolean; resealed?: boolean; opened_once?: boolean; board_count?: number;
  board?: number; broken_board?: number | null; board_label?: string; tag?: string;
  industry?: string; theme?: string; group?: string; themes?: string[]; themes_date?: string;
  topic_label?: string; first_limit_at?: string; last_limit_at?: string; limit_type?: string;
  open_count?: number | null; amount?: number | null; turnover_rate?: number | null;
  float_cap?: number | null; seal_amount?: number | null; prev_close?: number | null;
  limit_price?: number | null; quote_at?: string; lhb_net?: number | null; lhb_who?: string[];
  line?: MinutePoint[]; state?: 'sealed' | 'opened' | 'fallen' | 'waiting';
}
export interface LimitBoard extends Provenance {
  date: string; market_status: string; available: boolean; total_count: number;
  active_count: number; opened_count: number; seal_rate: number; observed_at: string;
  stocks: LimitStock[]; fallen: LimitStock[]; waiting: LimitStock[]; watch: LimitStock[];
  suspended?: LimitStock[]; error?: string; errors?: Record<string, string>;
  history: { date: string; total: number; sealed: number; highest: number }[];
  promotion: { label: string; promoted: number; base: number }[];
}
export interface Quote { symbol: string; name: string; price: number | null; change_percent: number | null; decimals?: number; url?: string; quote_at?: string }
export interface Overseas extends Provenance {
  industry: { meta?: { generated_at: string; stale: boolean }; session?: { default_view: string; views: { key: string; label: string }[] };
    sectors: { id: string; name: string; symbol?: string; url?: string; regular: { change_percent: number | null }; extended?: { change_percent: number | null } }[] };
  indicators: { commodities: { items: Quote[] }; groups: { title: string; items: Quote[] }[] };
  errors?: Record<string, string>;
}
export interface Daily {
  lhb: Provenance & { available: boolean; date: string; observed_at: string; institution_net: number; connect_net: number; count: number;
    seats: { key: string; alias: string; net: number; stocks: { code: string; name: string; board_count: number; limit_broken: boolean }[] }[] } | null;
  futures: Provenance & { partial?: boolean; date: string; updated_at: string; member: string; total: { net: number; net_change: number; long: number; short: number };
    series: { date: string; net: number; net_change: number }[] } | null;
  calendar?: Provenance & { macro: { date: string; time: string; title: string }[] } | null;
  errors?: Record<string, string>;
}
export interface Etf extends Provenance {
  date: string; status: string; errors?: Record<string, string>; updated_at: string; amount: number; minutes: [string, number][];
  peak_window: { start: string; end: string; ratio: number | null; amount: number } | null;
  windows: { start: string; end: string; ratio: number | null; amount: number }[];
}
export function reviewRequest<T>(resource: string, date: string, signal: AbortSignal) {
  return fetchAPI<ReviewResponse<T>>(`/market-review/${resource}${date ? `?date=${encodeURIComponent(date)}` : ''}`, { signal })
}
export const pct = (value?: number | null) => value == null || !Number.isFinite(value) ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(2)}%`
const EXCHANGE_TIMEZONE = 'Asia/Shanghai'
export const exchangeDate = () => new Intl.DateTimeFormat('en-CA', { timeZone: EXCHANGE_TIMEZONE, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
export const clock = (value?: string) => value && /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(value) ? value : !value || !Number.isFinite(Date.parse(value)) ? '—' : new Intl.DateTimeFormat('en-GB', { timeZone: EXCHANGE_TIMEZONE, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(value))
export function pool(board: LimitBoard): LimitStock[] {
  return board.stocks.map(stock => ({ ...stock, state: stock.active ? 'sealed' : 'opened' }))
}
export function ladderRows(board: LimitBoard): { height: number; sealed: number; stocks: LimitStock[] }[] {
  const all = [...pool(board), ...(board.fallen || []).map(s => ({ ...s, state: 'fallen' as const })),
    ...(board.waiting || []).map(s => ({ ...s, state: 'waiting' as const })),
    ...(board.watch || []).map(s => ({ ...s, board: 2, state: 'waiting' as const }))]
  const rows = new Map<number, LimitStock[]>()
  for (const stock of all) {
    const height = stock.state === 'sealed' ? stock.board_count ?? 1
      : stock.broken_board ?? stock.board ?? stock.board_count ?? 1
    if (height < 2) continue
    const stocks = rows.get(height) ?? []
    if (!stocks.some(s => s.code === stock.code)) stocks.push(stock)
    rows.set(height, stocks)
  }
  return [...rows].sort(([a], [b]) => b - a).map(([height, stocks]) => ({ height,
    sealed: stocks.filter(s => s.state === 'sealed').length,
    stocks: stocks.sort((a, b) => Number(b.state === 'sealed') - Number(a.state === 'sealed') ||
      Number(b.state === 'opened') - Number(a.state === 'opened') ||
      (a.state === 'waiting' ? (b.change_percent ?? -Infinity) - (a.change_percent ?? -Infinity)
        : (a.last_limit_at ?? '').localeCompare(b.last_limit_at ?? ''))),
  }))
}
export function groupStocks(stocks: LimitStock[]) {
  const groups = new Map<string, LimitStock[]>()
  stocks.forEach(stock => { const key = stock.group || stock.industry || '—'; groups.set(key, [...(groups.get(key) ?? []), stock]) })
  return [...groups].sort((a, b) => b[1].length - a[1].length).map(([name, items]) => ({ name,
    stocks: items.sort((a, b) => Number(!!b.active) - Number(!!a.active) || (b.board_count ?? 1) - (a.board_count ?? 1) || (a.last_limit_at ?? '').localeCompare(b.last_limit_at ?? '')) }))
}
