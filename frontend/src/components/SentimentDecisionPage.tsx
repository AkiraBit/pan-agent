import { useTranslation } from 'react-i18next'
import type { Evidence, SentimentOverview } from '@panwatch/api/emotion'
import { Button } from '@panwatch/base-ui/components/ui/button'
import SentimentCycleChart from './SentimentCycleChart'
import { SentimentReportExport } from './SentimentReportDetails'
import { emotionStamp } from './EmotionBlocks'

export default function SentimentDecisionPage({ overview: p, onEvidence }: { overview: SentimentOverview; onEvidence: (e: Evidence) => void }) {
  const { t } = useTranslation('emotion')
  const d = p.analysis.decision
  if (!d) return null
  const rows = ['cycle_note', 'short_term', 'index_context', 'structure', 'theme_verdict', 'today_strategy', 'buy_point_verdict'] as const
  return <div className="space-y-5" data-testid="sentiment-decision-page">
    <section className="rounded-2xl border bg-card p-5 sm:p-7">
      <h2 className="text-xl sm:text-2xl font-semibold">{t('overview.decision.title')}</h2>
      <p className="text-xs text-muted-foreground mt-2">{p.trade_date} · {t(p.intraday ? 'overview.intraday' : 'overview.closed')}</p>
      <div className="flex flex-wrap items-center gap-3 mt-5"><span className="rounded-full border px-3 py-1 text-xs text-muted-foreground">{t('overview.decision.confidence')} · {t(`overview.decision.${d.confidence}`)}</span><strong className="rounded-xl bg-primary/10 text-primary px-4 py-3">{p.analysis.stage.stages.map(s => t(`overview.stages.${s}`)).join(' ↔ ')}</strong></div>
    </section>
    <section className="rounded-2xl border bg-card p-4 sm:p-7">
      <h3 className="text-lg font-semibold border-l-4 border-primary pl-3">{t('overview.decision.conclusion')}</h3>
      <div className="rounded-xl border border-primary/20 bg-primary/5 p-4 sm:p-5 mt-4">
        <div className="flex flex-wrap items-center gap-3"><h4 className="font-semibold text-primary">{t('overview.decision.today')}</h4><span className="rounded-full bg-primary text-primary-foreground px-3 py-1 text-xs">{d.rhythm}</span></div>
        <p className="font-medium leading-7 mt-3">{d.assessment}</p>
        <dl className="space-y-4 mt-5">{rows.map(key => <div className="grid grid-cols-[5.5rem_minmax(0,1fr)] sm:grid-cols-[7rem_minmax(0,1fr)] gap-3 text-sm leading-7" key={key}><dt className="text-muted-foreground">{t(`overview.decision.${key}`)}</dt><dd className="whitespace-pre-line break-words">{d[key]}</dd></div>)}</dl>
      </div>
      <div className="mt-4"><SentimentCycleChart position={p.analysis.stage} compact /></div>
    </section>
    <section className="rounded-2xl border bg-card p-4 sm:p-7">
      <h3 className="text-lg font-semibold border-l-4 border-primary pl-3">{t('overview.decision.tomorrow')}</h3>
      <h4 className="text-lg font-medium mt-4">{d.tomorrow_title}</h4><p className="text-sm leading-7 text-muted-foreground mt-2">{d.tomorrow_expectation}</p>
      <h4 className="font-semibold mt-6 mb-3">{t('overview.decision.opportunities')}</h4>
      {d.paths.map(path => <div key={path.side} className="grid grid-cols-[3rem_minmax(0,1fr)] gap-3 text-sm leading-7 mt-3"><strong className="text-primary">{t(`overview.decision.${path.side}`)}</strong><div><p><b>{t('overview.decision.trigger')}</b> {path.trigger}</p><p className="text-muted-foreground"><b>{t('overview.decision.cancel')}</b> {path.invalidation}</p></div></div>)}
      <h4 className="font-semibold mt-6 mb-3">{t('overview.decision.boundaries')}</h4>
      <div className="space-y-3">{d.boundaries.map((b, i) => <article className="border rounded-xl border-l-4 p-4" key={i}><h5 className="font-medium text-sm">{b.topic}</h5><ul className="list-disc pl-4 mt-2 space-y-2 text-sm leading-7"><li>{b.strengthens}</li><li>{b.invalidates}</li></ul></article>)}</div>
      <h4 className="font-semibold mt-6 mb-3">{t('overview.decision.actions')}</h4><ul className="list-disc pl-4 text-sm leading-7 space-y-2">{d.actions.map((a, i) => <li key={i}>{a}</li>)}</ul>
    </section>
    <section className="rounded-2xl border bg-card p-4 sm:p-7">
      <h3 className="text-lg font-semibold border-l-4 border-primary pl-3">{t('overview.decision.focus')}</h3>
      {d.paths.map(path => <article key={path.side} className="rounded-xl border border-l-4 border-l-primary/60 p-4 sm:p-5 mt-4">
        <h4 className="font-semibold text-primary">{t(`overview.decision.${path.side}`)} · {path.title}</h4><p className="text-sm leading-7 mt-2">{path.action}</p>
        <div className="flex flex-wrap gap-2 mt-3">{path.sectors.map(s => <span key={s} className="rounded-full border px-3 py-1 text-xs text-muted-foreground">{s}</span>)}</div>
        {path.candidates.map(stock => <div key={stock.symbol} className="rounded-xl border p-4 mt-3 text-sm leading-7"><div className="flex flex-wrap items-center gap-2"><strong className="text-base">{stock.name}</strong><span className="text-xs text-muted-foreground">{stock.symbol}</span><span className="text-xs rounded-full bg-primary/10 text-primary px-3 py-1">{stock.role}</span></div><p className="mt-2">{stock.reason}</p><p><b>{t('overview.decision.trigger')}</b> {stock.trigger}</p><p className="text-muted-foreground"><b>{t('overview.decision.cancel')}</b> {stock.invalidation}</p></div>)}
      </article>)}
    </section>
    <SentimentReportExport runId={p.run_id} />
    <details className="rounded-xl border bg-card p-4"><summary className="cursor-pointer text-sm text-muted-foreground">{t('overview.decision.sources')}</summary><div className="mt-4 space-y-4">
      <ul className="text-sm leading-7 list-disc pl-4">{p.analysis.supports.map((c, i) => <li key={i}>{c.text}</li>)}</ul>
      <div className="space-y-2">{p.evidence.map(e => <div className="flex flex-wrap items-center gap-x-3 text-xs" key={e.id}><Button size="sm" variant="ghost" className="h-auto whitespace-normal text-left" onClick={() => onEvidence(e)}>{e.title}</Button><span className="text-muted-foreground">{e.source} · {emotionStamp(e.observed_at)}</span></div>)}</div>
      <ul className="text-xs leading-6 text-muted-foreground list-disc pl-4">{p.analysis.limitations.map((s, i) => <li key={i}>{s}</li>)}</ul>
    </div></details>
  </div>
}
