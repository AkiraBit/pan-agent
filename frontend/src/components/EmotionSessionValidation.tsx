import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@panwatch/base-ui/components/ui/button'
import { useToast } from '@panwatch/base-ui/components/ui/toast'
import { useConfirm } from '@panwatch/base-ui/components/ui/confirm-dialog'
import { emotionApi, type SessionValidation } from '@panwatch/api/emotion'
import { EmotionCard, emotionStamp } from './EmotionBlocks'
import { formatNumber } from '@/i18n/format'

export default function EmotionSessionValidation({ target }: { target: string }) {
  const { t } = useTranslation('emotion'), { toast } = useToast(), requestConfirm = useConfirm()
  const [data, setData] = useState<SessionValidation | null>(null), [busy, setBusy] = useState(false), [failed, setFailed] = useState(false)
  const load = useCallback(async (signal?: AbortSignal) => { if (!target) return; try { const value = await emotionApi.sessionValidation(target, signal); if (!signal?.aborted) { setData(value); setFailed(false) } } catch { if (!signal?.aborted) setFailed(true) } }, [target])
  useEffect(() => { setData(null); const c = new AbortController(); void load(c.signal); const timer = window.setInterval(() => void load(c.signal), 5000); return () => { c.abort(); window.clearInterval(timer) } }, [load])
  const toggle = async () => {
    if (!data || !await requestConfirm(t(data.enabled ? 'validation.pauseConfirm' : 'validation.armConfirm'))) return
    setBusy(true)
    try { setData(await emotionApi.armSessionValidation(target, !data.enabled)); toast(t('saved'), 'success') }
    catch { toast(t('validation.actionFailed'), 'error') }
    finally { setBusy(false) }
  }
  const exportAudit = () => { if (!data) return; const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })); const a = document.createElement('a'); a.href = url; a.download = `panwatch-session-${target}.json`; a.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000) }
  return <EmotionCard title={t('validation.title')} extra={<div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={!data} onClick={exportAudit}>{t('validation.export')}</Button><Button size="sm" disabled={busy || !data} onClick={() => void toggle()}>{t(data?.enabled ? 'validation.pause' : 'validation.arm')}</Button></div>}>
    <p className="text-sm text-muted-foreground leading-7">{t('validation.hint')}</p>
    {failed && <p role="alert" className="text-sm mt-3">{t('loadFailed')}</p>}
    {data && <div className="space-y-5 mt-5"><div className="grid sm:grid-cols-3 gap-3">{[[t('validation.day'), data.trade_date], [t('validation.nextDay'), data.next_trade_date || '—'], [t('validation.heartbeat'), emotionStamp(data.heartbeat_at)]].map(([label, value]) => <div key={label} className="rounded-xl bg-accent/30 p-4"><p className="text-xs text-muted-foreground">{label}</p><p className="text-sm mt-2">{value}</p></div>)}</div>
      <p className="text-sm font-medium">{t(`validationStatuses.${data.status}` as 'validationStatuses.not_armed')}</p>
      {!!data.warnings.length && <div className="border rounded-xl p-4 space-y-2">{data.warnings.map(w => <p className="text-xs leading-6 text-muted-foreground" key={w}>{t(`validationReasons.${w}` as 'validationReasons.auction_not_configured')}</p>)}</div>}
      <div className="space-y-3">{data.checkpoints.map(c => <article key={c.id} className="rounded-xl border p-4"><div className="flex flex-wrap justify-between gap-2"><h3 className="text-sm font-medium">{t(`validationSteps.${c.id}` as 'validationSteps.calendar')}</h3><span className="text-xs rounded-md bg-accent px-2 py-1">{t(`validationStates.${c.status}` as 'validationStates.pending')}</span></div><p className="text-xs text-muted-foreground leading-6 mt-2">{t(`validationReasons.${c.reason}` as 'validationReasons.awaiting_window')}</p>{c.samples != null && <p className="text-xs tabular-nums mt-2">{t('validation.sampleCoverage', { samples: c.samples, expected: c.expected ?? 0, coverage: formatNumber((c.coverage || 0) * 100, { maximumFractionDigits: 1 }), gap: c.max_gap_seconds ?? 0 })}</p>}{c.start && <p className="text-xs text-muted-foreground mt-2">{emotionStamp(c.start)} — {emotionStamp(c.end || null)}</p>}</article>)}</div>
      <details className="border rounded-xl p-4"><summary className="cursor-pointer text-sm font-medium">{t('validation.transitions')}</summary><div className="max-h-64 overflow-y-auto scrollbar space-y-3 mt-3">{data.events.map((e, i) => <div key={i} className="text-xs leading-6"><p>{emotionStamp(e.at)} · {t(`validationEvents.${e.type}` as 'validationEvents.armed')}</p>{e.states && <p className="text-muted-foreground">{Object.entries(e.states).map(([key, state]) => `${t(`validationSteps.${key}` as 'validationSteps.calendar')}：${t(`validationStates.${state}` as 'validationStates.pending')}`).join(' · ')}</p>}</div>)}</div></details>
    </div>}
  </EmotionCard>
}
