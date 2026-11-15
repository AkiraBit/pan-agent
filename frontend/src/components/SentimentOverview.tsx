import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Activity, ArrowUpRight, RefreshCw } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@panwatch/base-ui/components/ui/button'
import { emotionApi, type Evidence, type SentimentOverviewState } from '@panwatch/api/emotion'
import { formatNumber } from '@/i18n/format'
import SentimentCycleChart from './SentimentCycleChart'
import { EmotionCard, emotionStamp } from './EmotionBlocks'

const number = (v: number | null | undefined, suffix = '') => v == null ? '—' : formatNumber(v, { maximumFractionDigits: 2 }) + suffix

export default function SentimentOverview({ inputVersion, onEvidence }: { inputVersion: number; onEvidence: (e: Evidence) => void }) {
  const { t, i18n } = useTranslation('emotion')
  const [data, setData] = useState<SentimentOverviewState | null>(null)
  const [error, setError] = useState(false)
  const [busy, setBusy] = useState(false)
  const alive = useRef(true), pending = useRef(false), sequence = useRef(0)
  const language = i18n.resolvedLanguage === 'en-US' ? 'en-US' : 'zh-CN'
  const load = useCallback(async () => {
    const id = ++sequence.current
    try { const next = await emotionApi.overview(); if (alive.current && id === sequence.current) { setData(next); setError(false) } }
    catch { if (alive.current && id === sequence.current) setError(true) }
  }, [])
  const refresh = useCallback(async (force: boolean) => {
    if (pending.current) return
    pending.current = true; setBusy(true)
    try { await emotionApi.refreshOverview({ request_key: crypto.randomUUID(), language, force }); await load() }
    catch { if (alive.current) setError(true) }
    finally { pending.current = false; if (alive.current) setBusy(false) }
  }, [language, load])
  useEffect(() => { alive.current = true; void load(); const timer = window.setInterval(() => void load(), 5000); return () => { alive.current = false; sequence.current++; window.clearInterval(timer) } }, [load, inputVersion])
  useEffect(() => {
    if (data?.stale && data.can_analyze && !data.active_run && !busy && !error &&
        (!data.retry_after || data.retry_after <= data.server_time)) void refresh(false)
  }, [data, busy, error, refresh])
  const p = data?.overview, active = !!data?.active_run || busy
  const evidenceTitle = (e: Evidence) => e.id.startsWith('overview:') ? t(`overview.evidence.${e.id.slice(9)}`, { defaultValue: e.title }) : e.title
  const refs = (ids: string[]) => <div className="flex flex-wrap gap-1 mt-2">{ids.map(id => { const e = p?.evidence.find(e => e.id === id); return e ? <Button key={id} variant="ghost" size="sm" className="h-auto px-2 py-1 text-xs text-primary whitespace-normal text-left" onClick={() => onEvidence({ ...e, title: evidenceTitle(e) })}>{evidenceTitle(e)}<ArrowUpRight className="w-3 h-3 ml-1 shrink-0" /></Button> : null })}</div>
  return <div className="space-y-5" data-testid="sentiment-overview">
    <div className="flex flex-wrap justify-between gap-3 items-center"><div><h2 className="font-medium">{t('overview.latest')}</h2><p className="mt-1 text-xs text-muted-foreground">{p ? `${p.trade_date} · ${t(p.intraday ? 'overview.intraday' : 'overview.closed')} · ${t('overview.provider')}` : t('overview.sourceHint')}</p></div><Button onClick={() => void refresh(true)} disabled={!data?.can_analyze || active}><RefreshCw className={`w-4 h-4 mr-2 ${active ? 'animate-spin motion-reduce:animate-none' : ''}`} />{active ? t('running') : t('overview.refresh')}</Button></div>
    {!data?.can_analyze && data && <div className="rounded-xl border p-4 text-sm space-y-3"><p>{t(data.skill_enabled ? 'overview.connectionNeeded' : 'overview.skillDisabled')}</p><Button variant="outline" size="sm" asChild><Link to="/integrations/mcp?tab=skills&skill=analyze-a-share-sentiment">{t('overview.configure')}</Link></Button></div>}
    {(error || (data?.last_run && ['failed', 'interrupted'].includes(data.last_run.status) && !active)) && <div role="alert" className="rounded-xl border border-destructive/25 p-4 text-sm"><p>{t('overview.failed')}</p><p className="text-xs text-muted-foreground mt-2">{t('overview.failedHint')}</p><Button variant="ghost" size="sm" className="mt-2" onClick={() => void load()}>{t('retry')}</Button></div>}
    {active && <div role="status" className="rounded-xl border border-primary/20 bg-primary/5 p-4 text-sm flex gap-3 items-center"><Activity className="w-4 h-4 text-primary" /><span>{t('overview.running')}</span></div>}
    {p && data?.stale && <p role="status" className="text-xs text-muted-foreground rounded-xl border p-3">{t('overview.stale', { date: p.trade_date, time: emotionStamp(p.as_of) })}</p>}
    {!p && <section className="rounded-2xl border bg-card p-8"><h3 className="font-semibold">{t('overview.empty')}</h3><p className="text-sm leading-7 text-muted-foreground mt-3">{t('overview.emptyHint')}</p></section>}
    {p && <>
      <section className="rounded-2xl border border-primary/20 bg-gradient-to-br from-primary/5 to-card p-5 sm:p-6"><div className="flex flex-wrap items-center gap-2 text-xs"><span className="rounded-full border px-3 py-1 text-primary">{t(`overview.directions.${p.analysis.direction}`)}</span><span className="text-muted-foreground">{t('overview.asOf', { time: emotionStamp(p.as_of) })}</span></div><h2 className="text-xl sm:text-2xl font-semibold mt-4 leading-snug">{p.analysis.title}</h2><p className="text-sm leading-7 text-muted-foreground mt-3">{p.analysis.summary}</p><p className="text-xs leading-6 text-muted-foreground mt-3">{p.analysis.direction_reason}</p></section>
      <SentimentCycleChart position={p.analysis.stage} />
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">{([
        ['rising', p.metrics.breadth.rising, ''], ['falling', p.metrics.breadth.falling, ''], ['median', p.metrics.breadth.median, '%'], ['temperature', p.temperature.quality === 'available' ? p.temperature.temperature : null, ''],
      ] as const).map(([key, value, suffix]) => <div key={key} className="rounded-xl border bg-card p-4"><p className="text-xs text-muted-foreground">{t(`overview.metrics.${key}`)}</p><p className="text-2xl font-semibold tabular-nums mt-2">{number(value, suffix)}</p>{key === 'temperature' && <p className="text-[10px] text-muted-foreground mt-2">{t('overview.temperatureHint')}</p>}</div>)}</div>
      <p className="text-xs text-muted-foreground leading-6">{t('overview.coverage', { valid: p.coverage.valid, total: p.coverage.directory_total, excluded: p.coverage.excluded_st, missing: p.coverage.missing_or_stale, halted: p.coverage.excluded_halted, unsupported: p.coverage.excluded_unsupported ?? 0, directoryMissing: p.coverage.directory_missing })} · {t(p.coverage.status === 'complete' ? 'overview.complete' : 'overview.partial')}</p>
      {!!p.indices.length && <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">{p.indices.map(index => <div key={index.symbol} className="rounded-xl bg-accent/30 p-4"><p className="text-xs text-muted-foreground">{t(`overview.indices.${index.symbol.replace('.', '_')}` as 'overview.indices.000001_SH')}</p><div className="flex flex-wrap items-baseline gap-2 mt-2"><span className="font-medium tabular-nums">{number(index.price)}</span><span className={`text-xs tabular-nums ${index.change_pct > 0 ? 'text-market-up' : index.change_pct < 0 ? 'text-market-down' : 'text-muted-foreground'}`}>{index.change_pct > 0 ? '+' : ''}{number(index.change_pct, '%')}</span></div></div>)}</div>}
      <div className="grid md:grid-cols-2 gap-4">{(['loss_relief', 'profit_diffusion'] as const).map(key => <EmotionCard key={key} title={t(`overview.${key}`)}><span className="text-xs text-primary">{t(`overview.directions.${p.analysis[key].state}`)}</span><p className="text-sm leading-7 mt-3">{p.analysis[key].explanation}</p>{refs(p.analysis[key].evidence_ids)}</EmotionCard>)}</div>
      <EmotionCard title={t('overview.boardTitle')}><div className="overflow-x-auto scrollbar"><table className="w-full text-sm"><thead><tr className="text-xs text-muted-foreground">{['board', 'sample', 'positive', 'median', 'strong', 'weak'].map(k => <th key={k} className="text-left font-normal pb-3 px-2 whitespace-nowrap">{t(`overview.columns.${k}` as 'overview.columns.board')}</th>)}</tr></thead><tbody>{p.metrics.boards.map(b => <tr key={b.board} className="border-t"><td className="py-3 px-2 whitespace-nowrap">{t(`overview.boards.${b.board}`)}</td><td className="px-2">{b.valid} / {b.directory_count}</td><td className="px-2">{number(b.positive_ratio == null ? null : b.positive_ratio * 100, '%')}</td><td className="px-2">{number(b.median, '%')}</td><td className="px-2">{number(b.strong_count)}</td><td className="px-2">{number(b.weak_count)}</td></tr>)}</tbody></table></div><p className="text-xs text-muted-foreground leading-6 mt-4">{t('overview.proxyHint')}</p></EmotionCard>
      <div className="grid md:grid-cols-2 gap-4">{p.analysis.groups.map(g => <EmotionCard key={g.group} title={`${g.group} · ${t(`overview.groups.${g.group}`)}`} extra={<span className="text-xs text-muted-foreground">{t(`overview.groupStatus.${g.status}`)}</span>}><p className="text-sm leading-7">{g.explanation}</p>{refs(g.evidence_ids)}</EmotionCard>)}</div>
      <div className="grid md:grid-cols-2 gap-4">{(['supports', 'counters'] as const).map(key => <EmotionCard key={key} title={t(key)}><ul className="space-y-4">{p.analysis[key].map((c, i) => <li key={i} className="text-sm leading-7">{c.text}{refs(c.evidence_ids)}</li>)}</ul></EmotionCard>)}</div>
      <EmotionCard title={t('overview.nextChecks')}><div className="space-y-4">{p.analysis.next_checks.map((c, i) => <article key={i} className="rounded-xl border p-4"><span className="text-xs text-primary">{c.window}</span><p className="text-sm font-medium mt-2">{c.observe}</p><p className="text-xs leading-6 text-muted-foreground mt-2">{t('overview.strengthens')}：{c.strengthens}</p><p className="text-xs leading-6 text-muted-foreground">{t('invalidates')}：{c.invalidates}</p></article>)}</div></EmotionCard>
      <EmotionCard title={t('overview.limitations')}><ul className="list-disc pl-4 text-sm text-muted-foreground leading-7 space-y-2">{p.analysis.limitations.map((item, i) => <li key={i}>{item}</li>)}</ul><p className="text-xs text-muted-foreground mt-5 border-t pt-4">{t('overview.analyzed', { time: emotionStamp(p.analyzed_at) })} · {p.model_label}</p></EmotionCard>
    </>}
  </div>
}
