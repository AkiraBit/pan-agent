import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@panwatch/base-ui/components/ui/button'
import { useConfirm } from '@panwatch/base-ui/components/ui/confirm-dialog'
import { useToast } from '@panwatch/base-ui/components/ui/toast'
import { emotionApi, type EmotionPage, type EmotionPublication, type Evidence, type Lifecycle } from '@panwatch/api/emotion'
import { EmotionCard, emotionStamp } from './EmotionBlocks'
import { formatNumber } from '@/i18n/format'

const value = (n: number | null | undefined) => n == null ? '—' : formatNumber(n, { maximumFractionDigits: 3 })
export default function EmotionLifecycle({ publication: p, page, active, onRefresh, onEvidence }: {
  publication: EmotionPublication; page: EmotionPage; active: boolean; onRefresh: () => Promise<void>; onEvidence: (e: Evidence) => void
}) {
  const { t } = useTranslation('emotion')
  const { toast } = useToast(), requestConfirm = useConfirm()
  const [data, setData] = useState<Lifecycle | null>(null), [failed, setFailed] = useState(false)
  const [busy, setBusy] = useState(false)
  const load = useCallback(async (signal?: AbortSignal) => {
    try { const next = await emotionApi.lifecycle(p.id, signal); if (!signal?.aborted) { setData(next); setFailed(false) } }
    catch { if (!signal?.aborted) setFailed(true) }
  }, [p.id])
  useEffect(() => { setData(null); const c = new AbortController(); void load(c.signal); const timer = window.setInterval(() => void load(c.signal), 4000); return () => { c.abort(); window.clearInterval(timer) } }, [load])
  const action = async (fn: () => Promise<unknown>) => { setBusy(true); try { await fn(); await load(); await onRefresh() } catch { toast(t('lifecycle.actionFailed'), 'error') } finally { setBusy(false) } }
  const toggle = async () => {
    if (data?.monitor?.status === 'active' && !await requestConfirm(t('lifecycle.pauseConfirm'))) return
    await action(() => emotionApi.monitor(p.id, data?.monitor?.status !== 'active'))
  }
  const review = data?.review
  const last = data?.latest
  const name = (symbol: string) => p.facts.quotes.find(q => q.symbol === symbol)?.name || symbol
  const status = data?.monitor?.status || 'off'
  const visible = ['overview', 'monitor', 'review'].includes(page)
  if (!visible) return null
  return <div className="space-y-5">
    {failed && <p role="alert" className="text-sm text-muted-foreground">{t('loadFailed')}</p>}
    {page !== 'review' && <EmotionCard title={t('pages.monitor')} extra={<div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" asChild><a href="/datasources">{t('lifecycle.configure')}</a></Button><Button size="sm" disabled={busy || !data} onClick={() => void toggle()}>{t(status === 'active' ? 'lifecycle.pause' : 'lifecycle.start')}</Button></div>}>
      <div className="grid sm:grid-cols-3 gap-3">{[
        [t('lifecycle.monitor'), t(`monitorStates.${status}` as 'monitorStates.active')],
        [t('lifecycle.samples'), String(data?.sample_count ?? 0)],
        [t('lifecycle.lastSample'), emotionStamp(data?.monitor?.last_sample_at || null)],
      ].map(([label, content]) => <div key={label} className="rounded-xl bg-accent/40 p-4"><p className="text-xs text-muted-foreground">{label}</p><p className="text-sm font-medium mt-2">{content}</p></div>)}</div>
      <p className="text-xs text-muted-foreground leading-6 mt-4">{t('lifecycle.samplingHint')}</p>
      {data?.monitor?.last_error && <p role="alert" className="text-sm mt-3">{t('lifecycle.samplingFailed')}</p>}
      {page === 'monitor' && <div className="space-y-4 mt-5">{p.analysis.conditions.map(c => { const observed = last?.evaluations.find(e => e.id === c.id); return <article key={c.id} className="rounded-xl border p-4"><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-medium">{c.title}</h3><span className="text-xs rounded-md bg-accent px-2 py-1">{t(`states.${observed?.state || 'waiting'}`)}</span></div><p className="text-xs text-muted-foreground mt-2">{t(`windows.${c.window}`)} · {observed ? t(`reasons.${observed.reason}` as 'reasons.window_not_reached') : t('reasons.window_not_reached')}</p><p className="text-sm leading-7 mt-3">{c.criterion}</p>{c.rule && <p className="text-xs text-muted-foreground mt-2">{t('lifecycle.rule', { mode: c.rule.mode === 'all' ? t('lifecycle.all') : t('lifecycle.any'), seconds: c.rule.persistence_seconds })}</p>}<div className="space-y-2 mt-3">{observed?.checks.map((check, i) => <p key={i} className="text-xs tabular-nums">{name(check.symbol)} · {t(`metrics.${check.metric}` as 'metrics.price')} {check.operator === 'gte' ? '≥' : '≤'} {value(check.value)} · {t('lifecycle.actual')} {value(check.observed_value)} · {emotionStamp(check.source_time)}</p>)}</div><p className="text-xs text-muted-foreground leading-6 mt-3">{t('invalidates')}：{c.invalidation}</p></article> })}</div>}
    </EmotionCard>}
    {page === 'monitor' && <><EmotionCard title={t('lifecycle.auction')}><p className="text-sm font-medium">{t(`auctionStates.${last?.auction.status || (data?.auction_source.enabled ? 'waiting' : 'not_configured')}` as 'auctionStates.not_configured')}</p><p className="text-xs text-muted-foreground leading-6 mt-2">{t('lifecycle.auctionHint')}</p><div className="grid sm:grid-cols-2 gap-3 mt-4">{last?.auction.quotes.map(q => <article key={q.symbol} className="rounded-xl border p-4"><h3 className="text-sm font-medium">{name(q.symbol)} · {t(q.final ? 'lifecycle.finalAuction' : 'lifecycle.indicative')}</h3><p className="text-xl font-semibold mt-3 tabular-nums">{value(q.reference_price)}</p><p className="text-xs mt-3">{t('lifecycle.matched')} {value(q.matched_volume_shares)}</p><p className="text-xs mt-2">{t('lifecycle.unmatched')} {value(q.unmatched_volume_shares)} · {t(`auctionSides.${q.unmatched_side}` as 'auctionSides.buy')}</p><p className="text-xs text-muted-foreground mt-3">{emotionStamp(q.source_time)}</p></article>)}</div></EmotionCard>
    <EmotionCard title={t('lifecycle.timeline')}><div className="max-h-72 overflow-y-auto scrollbar space-y-3">{data?.timeline.map(s => <div key={s.id} className="border-l-2 border-primary/30 pl-4"><p className="text-xs font-medium">{emotionStamp(s.observed_at)} · {t(`phases.${s.phase}` as 'phases.continuous')}</p><p className="text-xs text-muted-foreground mt-1">{Object.values(s.states).map(v => t(`states.${v}` as 'states.waiting')).join(' / ')}</p></div>)}{!data?.timeline.length && <p className="text-sm text-muted-foreground">{t('lifecycle.noSamples')}</p>}</div></EmotionCard></>}
    {page === 'review' && <>
      <EmotionCard title={t('lifecycle.postmarket')} extra={!review && <Button size="sm" disabled={busy || active || !data?.sample_count} onClick={() => void action(() => emotionApi.review(p.id, crypto.randomUUID()))}>{t('lifecycle.generateReview')}</Button>}>
        {review ? <div className="space-y-5"><div><h3 className="text-lg font-semibold">{review.analysis.title}</h3><p className="text-xs text-muted-foreground mt-2">{emotionStamp(review.published_at)} · {review.model_label}</p><p className="text-sm leading-7 mt-3">{review.analysis.summary}</p></div><p className="text-xs text-muted-foreground">{t('lifecycle.reviewCoverage', { count: review.summary.sample_count })} · {t(review.summary.has_closing_sample ? 'lifecycle.withClose' : 'lifecycle.noClose')} · {t(review.summary.prospective_plan ? 'lifecycle.prospective' : 'lifecycle.retrospective')}</p>{review.analysis.findings.map(f => <article key={f.condition_id} className="rounded-xl border p-4"><div className="flex flex-wrap justify-between gap-2 text-sm"><h4 className="font-medium">{p.analysis.conditions.find(c => c.id === f.condition_id)?.title}</h4><span>{t(`assessments.${f.assessment}`)}</span></div><p className="text-sm leading-7 mt-3">{f.explanation}</p><div className="flex flex-wrap gap-2 mt-2">{f.evidence_ids.map(id => { const e = review.evidence.find(e => e.id === id); return e ? <Button size="sm" variant="ghost" key={id} onClick={() => onEvidence(e)}>{emotionStamp(e.observed_at)}</Button> : null })}</div></article>)}<h3 className="text-sm font-semibold">{t('lifecycle.lessons')}</h3>{review.analysis.lessons.map((v, i) => <p key={i} className="text-sm leading-7">{v}</p>)}<h3 className="text-sm font-semibold">{t('lifecycle.nextDay')}</h3>{review.analysis.next_day_focus.map((v, i) => <p key={i} className="text-sm leading-7">{v}</p>)}<p className="text-sm leading-7 bg-accent/30 rounded-xl p-4">{review.analysis.memory_summary}</p></div> : <p className="text-sm text-muted-foreground leading-7">{t('lifecycle.reviewHint')}</p>}
      </EmotionCard><EmotionCard title={t('lifecycle.reviewMemory')}><div className="space-y-4">{p.review_memory_input?.map(m => <article key={m.review_id} className="border rounded-xl p-4"><h3 className="text-sm font-medium">{m.target_trade_date}</h3><p className="text-sm leading-7 mt-2">{m.memory_summary}</p>{m.open_questions.map((q, i) => <p className="text-xs text-muted-foreground leading-6 mt-2" key={i}>{q}</p>)}</article>)}{!p.review_memory_input?.length && <p className="text-sm text-muted-foreground">{t('lifecycle.noReviewMemory')}</p>}</div></EmotionCard>
    </>}
  </div>
}
