import type { EtfIntraday, EtfLinkedAnalysis, EtfTurnoverBaseline } from '@panwatch/api/etf'
import { ETF_SESSION_MINUTES } from './session'

export type MinuteRange = [string, string]
export function rangeAmounts(points: Record<string, number | null>, range: MinuteRange) {
  const minutes = ETF_SESSION_MINUTES.filter(minute => minute >= range[0] && minute <= range[1])
  const values = minutes.map(minute => points[minute])
  return minutes.length && values.every(value => value != null) ? values.reduce<number>((sum, value) => sum + value!, 0) : null
}
export function baselineAmount(cumulative: Record<string, number> | null | undefined, range: MinuteRange) {
  if (!cumulative) return null
  const before = ETF_SESSION_MINUTES[ETF_SESSION_MINUTES.indexOf(range[0]) - 1]
  const end = cumulative[range[1]], start = before ? cumulative[before] : 0
  return start != null && end != null ? end - start : null
}
export function selectTurnover(data: EtfIntraday, analysis: EtfLinkedAnalysis | undefined, group: string, baseline?: EtfTurnoverBaseline | null) {
  const selected = analysis?.groups.find(item => item.id === group)
  if (!selected) return { data, baseline }
  return {
    data: { ...data, symbols: selected.symbols, etf_count: selected.symbols.length,
      points: data.points.map(point => ({ ...point, turnover_cny: selected.points[point.minute] ?? null,
        etf_count: selected.points[point.minute] == null ? 0 : selected.symbols.length })) },
    baseline: selected.baseline ? { sessions: 5, cumulative_cny: selected.baseline } : null,
  }
}
