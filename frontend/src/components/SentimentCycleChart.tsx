import { useId } from 'react'
import { useTranslation } from 'react-i18next'
import type { SentimentStage, StagePosition } from '@panwatch/api/emotion'

const stages: SentimentStage[] = ['ice', 'repair', 'expansion', 'heat', 'divergence', 'retreat', 'ice']
const points = [[45, 224], [182, 181], [320, 105], [458, 48], [596, 104], [734, 188], [872, 225]]
const curve = 'M45 224 C100 223 140 204 182 181 S275 133 320 105 S412 48 458 48 S548 67 596 104 S680 169 734 188 S826 225 872 225'

export default function SentimentCycleChart({ position, compact = false }: { position: StagePosition; compact?: boolean }) {
  const { t } = useTranslation('emotion')
  const id = useId().replace(/:/g, '')
  const start = position.stages[0] ? stages.indexOf(position.stages[0]) : -1
  const end = position.kind === 'between' ? start + 1 : start
  const known = start >= 0 && position.kind !== 'unknown'
  const label = position.kind === 'between' ? t('overview.between', { from: t(`overview.stages.${position.stages[0]}`), to: t(`overview.stages.${position.stages[1]}`) }) :
    known ? t(`overview.stages.${position.stages[0]}`) : t('overview.unplaced')
  return <section className="rounded-2xl border bg-card p-5 sm:p-6" aria-label={t('overview.cycleTitle')}>
    <div className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs text-muted-foreground">{t('overview.cycleTitle')}</p><h3 className="mt-2 text-lg sm:text-xl font-semibold">{t('overview.current')} · {label}</h3></div>{!compact && <span className="rounded-full bg-primary/10 text-primary text-xs px-3 py-1.5">{t(`overview.certainty.${position.status}`)}</span>}</div>
    <div className="overflow-x-auto scrollbar mt-4">
      <svg viewBox="0 0 920 300" className="w-full min-w-[650px]" role="img" aria-label={t('overview.chartLabel', { position: label })}>
        <defs><linearGradient id={`${id}-area`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" className="text-primary" stopColor="currentColor" stopOpacity="0.13" /><stop offset="100%" className="text-primary" stopColor="currentColor" stopOpacity="0.01" /></linearGradient><clipPath id={`${id}-highlight`}><rect x={known ? points[start][0] - 12 : 0} y="0" width={known ? points[end][0] - points[start][0] + 24 : 0} height="245" /></clipPath></defs>
        {[80, 150, 225].map(y => <line key={y} x1="24" x2="894" y1={y} y2={y} className="stroke-border" strokeDasharray="3 6" />)}
        <path d={`${curve} L872 240 L45 240 Z`} fill={`url(#${id}-area)`} />
        {known && <rect x={points[start][0] - 14} y="30" width={points[end][0] - points[start][0] + 28} height="210" rx="14" className="fill-primary/10" />}
        <path d={curve} fill="none" className="stroke-muted-foreground/35" strokeWidth="3" />
        {known && <path d={curve} fill="none" className="stroke-primary" strokeWidth="5" strokeLinecap="round" clipPath={`url(#${id}-highlight)`} />}
        {points.map(([x, y], i) => <g key={i}><line x1={x} x2={x} y1={y + 10} y2="243" className="stroke-border" strokeDasharray="3 5" /><circle cx={x} cy={y} r={known && i >= start && i <= end ? 7 : 4.5} className={known && i >= start && i <= end ? 'fill-primary stroke-card' : 'fill-card stroke-muted-foreground/50'} strokeWidth="2.5" /><text x={x} y="264" textAnchor="middle" className={`${known && i >= start && i <= end ? 'fill-primary font-semibold' : 'fill-muted-foreground'} text-[12px]`}>{t(`overview.stages.${stages[i]}`)}</text></g>)}
        {known && <g><rect x={(points[start][0] + points[end][0]) / 2 - 26} y="4" width="52" height="22" rx="11" className="fill-primary" /><text x={(points[start][0] + points[end][0]) / 2} y="19" textAnchor="middle" className="fill-primary-foreground text-[11px] font-medium">{t('overview.current')}</text></g>}
        <text x="893" y="291" textAnchor="end" className="fill-muted-foreground text-[10px]">{t('overview.phaseOrder')}</text>
      </svg>
    </div>
    {!compact && <><p className="mt-2 text-sm leading-7">{position.rationale}</p><p className="mt-3 text-xs text-muted-foreground leading-6">{t('overview.chartHint')}</p></>}
  </section>
}
