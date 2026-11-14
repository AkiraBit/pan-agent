import { useCallback, useEffect, useState } from 'react'
import { Compass, RefreshCw, Clock3 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { fetchAPI } from '@panwatch/api/client'
import { Button } from '@panwatch/base-ui/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@panwatch/base-ui/components/ui/select'
import { formatDate, formatNumber } from '@/i18n/format'
import SpeculationTabs, { type Speculation } from '@/components/SpeculationTabs'
import type { shortTerm } from '@/i18n/locales/zh-CN/shortTerm'

type Phase = keyof typeof shortTerm.phases
type Quality = { status: keyof typeof shortTerm.status; count: number; expected: number | null; source_time?: number | null; freshness?: keyof typeof shortTerm.freshness }
type Breadth = { valid: number; rising: number; falling: number; flat: number; median: number | null }
type Theme = { code: string; name: string; change: number | null; state: keyof typeof shortTerm.states; breadth: Breadth; strong: number; limit_up: number | null; quality: Quality; leaders: { code: string; name: string; change: number }[] }
type Snapshot = {
  speculation?: Speculation
  id: number; captured_at: string; trade_date: string; phase: Phase; environment: keyof typeof shortTerm.environment
  market: Breadth & { quality: Quality }; concepts: Quality; themes: Theme[]
  sentiment: { counts: Record<'up' | 'down' | 'broken' | 'yesterday', number | null>; yesterday_mean: number | null; max_streak: number | null; break_rate: number | null; quality: Record<string, Quality> }
}
export type Observation = { snapshot: Snapshot | null; phase: Phase; server_time: string; collecting: boolean; retry_after: number; error: string | null; history: { id: number; captured_at: string }[] }
const stamp = (value: string | number) => formatDate(value, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', timeZoneName: 'short' })
const pct = (value: number | null) => value === null ? '—' : `${formatNumber(value, { maximumFractionDigits: 2 })}%`
const count = (value: number | null) => value === null ? '—' : formatNumber(value)

export default function ShortTermPage() {
  const { t } = useTranslation('shortTerm')
  const [data, setData] = useState<Observation | null>(null)
  const [selected, setSelected] = useState('latest')
  const [failed, setFailed] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const result = await fetchAPI<Observation>(`/short-term/overview${selected === 'latest' ? '' : `?snapshot_id=${selected}`}`, { signal })
      if (!signal?.aborted) { setData(result); setFailed(false) }
    } catch { if (!signal?.aborted) setFailed(true) }
  }, [selected])
  useEffect(() => {
    const controller = new AbortController()
    void load(controller.signal)
    const timer = window.setInterval(() => { void load(controller.signal) }, 5000)
    return () => { controller.abort(); window.clearInterval(timer) }
  }, [load])
  const refresh = async () => {
    setSubmitting(true)
    try { await fetchAPI('/short-term/refresh', { method: 'POST' }); await load() }
    catch { setFailed(true) }
    finally { setSubmitting(false) }
  }
  const snapshot = data?.snapshot
  const phase = data?.phase ?? 'unknown'
  const working = submitting || data?.collecting
  const old = !!snapshot && (new Date(data!.server_time).getTime() - new Date(snapshot.captured_at).getTime() > 600000)
  const quality = (q: Quality) => (
    <span className="text-xs text-muted-foreground leading-6">
      {t(`status.${q.status}`)} · {t('coverage', { count: q.count, expected: q.expected ?? '—' })}
      {q.freshness && <> · {t(`freshness.${q.freshness}`)}</>}
      {q.source_time && <span className="block">{t('timestamp', { time: stamp(q.source_time * 1000) })}</span>}
    </span>
  )
  const metric = (label: string, value: string, direction?: 'up' | 'down') => (
    <div key={label} className="rounded-xl bg-accent/35 p-3 min-w-0">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-1 text-xl font-semibold tabular-nums ${direction === 'up' ? 'text-market-up' : direction === 'down' ? 'text-market-down' : ''}`}>{value}</div>
    </div>
  )
  return (
    <div className="max-w-7xl mx-auto space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div><h1 className="text-2xl font-semibold flex items-center gap-2"><Compass className="text-primary w-6 h-6" />{t('title')}</h1><p className="mt-2 text-sm text-muted-foreground">{t('subtitle')}</p></div>
        <div className="flex flex-wrap items-center gap-2">
          {!!data?.history.length && <Select value={selected} onValueChange={setSelected}><SelectTrigger className="w-48" aria-label={t('history')}><SelectValue /></SelectTrigger><SelectContent><SelectItem value="latest">{t('latest')}</SelectItem>{data.history.map(h => <SelectItem key={h.id} value={String(h.id)}>{stamp(h.captured_at)}</SelectItem>)}</SelectContent></Select>}
          <Button onClick={refresh} disabled={!!working || !!data?.retry_after}><RefreshCw className={`w-4 h-4 mr-2 ${working ? 'animate-spin' : ''}`} />{working ? t('collecting') : t('refresh')}</Button>
        </div>
      </header>
      {failed && <div role="alert" className="card p-4 text-sm">{t('loadFailed')} <Button variant="ghost" onClick={() => { void load() }}>{t('retry')}</Button></div>}
      {data?.error && <p role="alert" className="text-sm text-destructive">{t('failed')}</p>}
      <section className="rounded-2xl border border-primary/20 bg-primary/5 p-5">
        <div className="flex items-center gap-2 text-xs font-medium text-primary"><Clock3 className="w-4 h-4" />{t('phase')} · {t(`phases.${phase}`)}</div>
        <p className="mt-2 text-base leading-7">{t(`steps.${phase}`)}</p>
        <div className="mt-4 border-t border-primary/10 pt-3"><h2 className="text-sm font-medium">{t('auctionTitle')}</h2><p className="mt-1 text-xs leading-6 text-muted-foreground">{t('auctionHint')}</p></div>
      </section>
      {snapshot ? <>
        <div className="flex flex-wrap justify-between gap-2 text-xs text-muted-foreground"><p>{t('asOf', { time: stamp(snapshot.captured_at), day: snapshot.trade_date })}</p><p>{t('source')}</p></div>
        {(selected !== 'latest' || old) && <p role="status" className="rounded-xl border p-3 text-sm">{t(selected !== 'latest' ? 'historical' : 'old')}</p>}
        <SpeculationTabs data={snapshot.speculation} />
        <details className="card p-5"><summary className="cursor-pointer font-medium text-sm">{t('spec.background')}</summary>
        <div className="grid lg:grid-cols-2 gap-5 mt-4">
          <section className="card p-5 space-y-4"><div className="flex flex-wrap justify-between gap-2"><h2 className="font-semibold">{t('market')}</h2><span className="text-sm text-primary">{t(`environment.${(old && selected === 'latest') || failed ? 'pending' : snapshot.environment}`)}</span></div>
            <div className="grid grid-cols-3 gap-2">{metric(t('rising'), snapshot.market.valid ? count(snapshot.market.rising) : '—', 'up')}{metric(t('falling'), snapshot.market.valid ? count(snapshot.market.falling) : '—', 'down')}{metric(t('flat'), snapshot.market.valid ? count(snapshot.market.flat) : '—')}</div>
            <div className="flex justify-between text-sm"><span>{t('median')} <strong className="ml-2">{pct(snapshot.market.median)}</strong></span><span className="text-muted-foreground">{t('valid', { count: snapshot.market.valid })}</span></div>
            {quality(snapshot.market.quality)}
            <p className="text-xs text-muted-foreground leading-6">{t('universeHint', { count: Math.max(0, snapshot.market.quality.count - snapshot.market.valid) })}</p>
          </section>
          <section className="card p-5 space-y-4"><h2 className="font-semibold">{t('sentiment')}</h2>
            <div className="grid grid-cols-3 gap-2">{(['up', 'down', 'broken'] as const).map(k => metric(t(k), count(snapshot.sentiment.counts[k])))}</div>
            <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm"><span>{t('yesterday')} <strong>{pct(snapshot.sentiment.yesterday_mean)}</strong></span><span>{t('breakRate')} <strong>{pct(snapshot.sentiment.break_rate === null ? null : snapshot.sentiment.break_rate * 100)}</strong></span></div>
            <p className="text-xs text-muted-foreground leading-6">{t('poolScope')}</p>
          </section>
        </div>
        </details>
        <details className="card p-5"><summary className="cursor-pointer font-medium text-sm">{t('quality')} · {t('methodology')}</summary><p className="mt-4 text-xs leading-6 text-muted-foreground">{t('method')}</p><div className="mt-4 grid sm:grid-cols-2 lg:grid-cols-3 gap-3"><div><p className="text-sm">{t('themes')}</p>{quality(snapshot.concepts)}</div>{Object.entries(snapshot.sentiment.quality).map(([k, q]) => <div key={k}><p className="text-sm">{t(k as 'up' | 'down' | 'broken' | 'yesterday')}</p>{quality(q)}</div>)}</div></details>
        <p className="text-xs text-muted-foreground">{t('snapshot')}</p>
      </> : <section className="card p-10 text-center"><h2 className="font-semibold">{t('empty')}</h2><p className="mt-3 text-sm leading-7 text-muted-foreground">{t('emptyHint')}</p></section>}
      {!!data?.retry_after && !working && <p className="text-xs text-muted-foreground">{t('cooldown', { seconds: data.retry_after })}</p>}
    </div>
  )
}
