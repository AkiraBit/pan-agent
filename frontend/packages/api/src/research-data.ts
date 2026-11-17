import { fetchAPI } from './client'
import type { FuyaoParameter } from './fuyao-rest'

export const researchWorkspaces = [
  'index_constituents', 'ipo', 'etf_adjusted_history', 'fund_holdings',
  'fund_research', 'fund_backtest', 'futures_research', 'options_research',
] as const
export type ResearchWorkspace = typeof researchWorkspaces[number]
export type ResearchView = {
  id: string; section: string; title: string; description: string
  fields: FuyaoParameter[]; chart: string | null
}
export type ResearchManifest = {
  views: ResearchView[]
  sources: { provider: string; name: string; priority: number; enabled: boolean; available: boolean }[]
  today: string
  last_trade_date: string | null
}
export type ResearchResult = { provider: string; source_name: string; result: unknown }
export type BacktestRule = { indicator_code: string; operator: string; value: number | string }
export type BacktestConditions = { buy: BacktestRule[]; sell: BacktestRule[] }

const base = '/research-data'
export const loadResearchWorkspace = (kind: ResearchWorkspace, signal: AbortSignal) =>
  fetchAPI<ResearchManifest>(`${base}/${kind}`, { signal })
export const loadResearchView = (kind: ResearchWorkspace, view: string, filters: Record<string, string>, signal: AbortSignal,
  conditions?: BacktestConditions) => fetchAPI<ResearchResult>(`${base}/${kind}/${encodeURIComponent(view)}`, {
  method: 'POST', body: JSON.stringify({ filters, ...(conditions ? { conditions } : {}) }), signal, timeoutMs: 30_000,
})
