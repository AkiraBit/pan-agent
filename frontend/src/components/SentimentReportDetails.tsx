import { useState } from 'react'
import { Download } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@panwatch/base-ui/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@panwatch/base-ui/components/ui/dialog'
import { emotionApi, type SentimentOverview } from '@panwatch/api/emotion'
import { EmotionCard, emotionStamp } from './EmotionBlocks'
import { formatNumber } from '@/i18n/format'

export function SentimentReportExport({ runId }: { runId: string }) {
  const { t } = useTranslation('emotion')
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)
  const [preview, setPreview] = useState<string | null>(null)
  const openPreview = async () => {
    setBusy(true); setFailed(false)
    try {
      const html = await emotionApi.previewOverview(runId)
      // srcdoc inherits the app URL as its base; keep evidence fragments inside
      // the sandboxed report instead of navigating the frame to the app route.
      setPreview(html.replace(/href="#/g, 'href="about:srcdoc#'))
    }
    catch { setFailed(true) }
    finally { setBusy(false) }
  }
  const download = async (format: 'html' | 'json') => {
    setBusy(true); setFailed(false)
    try { await emotionApi.downloadOverview(runId, format) }
    catch { setFailed(true) }
    finally { setBusy(false) }
  }
  return <div className="flex flex-wrap items-center gap-2">
    <Button variant="outline" size="sm" disabled={busy} onClick={() => void openPreview()}>{t('overview.report.preview')}</Button>
    <Button variant="outline" size="sm" disabled={busy} onClick={() => void download('html')}><Download className="w-4 h-4 mr-2" />{t('overview.report.exportHtml')}</Button>
    <Button variant="ghost" size="sm" disabled={busy} onClick={() => void download('json')}>{t('overview.report.exportJson')}</Button>
    {failed && <span role="alert" className="text-xs text-destructive">{t('overview.report.exportFailed')}</span>}
    <Dialog open={preview !== null} onOpenChange={open => { if (!open) setPreview(null) }}><DialogContent aria-describedby={undefined} className="max-w-6xl h-[90dvh] flex flex-col min-h-0"><DialogHeader><DialogTitle>{t('overview.report.preview')}</DialogTitle></DialogHeader><iframe title={t('overview.report.preview')} sandbox="" srcDoc={preview ?? ''} className="w-full flex-1 min-h-0 rounded-lg border" /></DialogContent></Dialog>
  </div>
}

export default function SentimentReportDetails({ overview }: { overview: SentimentOverview }) {
  const { t } = useTranslation('emotion')
  const report = overview.report
  if (!report) return null
  return <div className="space-y-4">
    <EmotionCard title={t('overview.report.validation')}>
      {!report.continuity.checks.length && <p className="text-sm text-muted-foreground leading-7">{t('overview.report.noRegistration')}</p>}
      <div className="space-y-3">{report.continuity.checks.map(c => <article key={c.id} className="rounded-xl border p-4">
        <div className="flex flex-wrap justify-between gap-2"><h4 className="text-sm font-medium">{c.observe}</h4><span className="text-xs text-primary">{t(`overview.report.states.${c.state}`)}</span></div>
        <p className="text-xs text-muted-foreground mt-2">{t('overview.report.registered', { at: emotionStamp(c.registered_at), day: c.target_trade_date ?? '—' })}</p>
        <p className="text-xs leading-6 mt-2">{t('overview.strengthens')}：{c.strengthens}</p>
        <p className="text-xs leading-6">{t('invalidates')}：{c.invalidates}</p>
        <p className="text-sm leading-7 mt-2">{t(`overview.report.reasons.${c.reason}` as 'overview.report.reasons.evaluated')}</p>
        {!!c.observations.length && <ul className="space-y-2 mt-2 text-xs text-muted-foreground">{c.observations.map((o, i) => <li key={i}>{t(`overview.report.metrics.${o.metric}`)} · {o.observed_value == null ? '—' : formatNumber(o.observed_value, { maximumFractionDigits: 4 })} / {o.operator} {o.value}<p>{o.basis} · {t('overview.report.unvalidated')}</p></li>)}</ul>}
      </article>)}</div>
    </EmotionCard>
    {report.revision && <EmotionCard title={t('overview.report.revision')}>
      <p className="text-xs text-muted-foreground">{emotionStamp(report.revision.previous_as_of)}</p>
      <p className="text-sm leading-7 mt-2">{report.revision.previous_title}</p>
      <p className="text-sm text-primary mt-2">{report.revision.previous_stage.stages.map(s => t(`overview.stages.${s}`)).join(' / ') || t('overview.unplaced')} → {report.revision.current_stage.stages.map(s => t(`overview.stages.${s}`)).join(' / ') || t('overview.unplaced')}</p>
      <p className="text-sm leading-7 mt-3">{report.revision.explanation}</p><p className="text-xs text-muted-foreground mt-3">{t('overview.report.immutable')}</p>
    </EmotionCard>}
    <EmotionCard title={t('overview.report.gaps')}><div className="grid md:grid-cols-2 gap-3">{report.data_gaps.map(g => <article className="rounded-xl border p-4" key={g.id}>
      <h4 className="text-sm font-medium">{t(`overview.report.gapLabels.${g.id}` as 'overview.report.gapLabels.themes', { defaultValue: g.label })}</h4>
      <p className="text-xs leading-6 text-muted-foreground mt-2">{g.impact}</p><p className="text-xs leading-6 mt-2">{t('overview.report.required')}：{g.required}</p>
    </article>)}</div><p className="text-xs text-muted-foreground leading-6 mt-4">{t('overview.report.execution')}</p></EmotionCard>
  </div>
}
