import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { marketSignTextClass } from '@/lib/market-colors'
import type { MinutePoint } from './data'
import { clock, pct } from './data'

export function Sparkline({ points, muted = false, large = false }: { points?: MinutePoint[]; muted?: boolean; large?: boolean }) {
  const { t } = useTranslation('marketReview')
  const [selected, setSelected] = useState<number | null>(null)
  const values = (points ?? []).filter(p => Number.isFinite(p.change_percent))
  if (values.length < 2) return large ? <p className="review-empty">{t('noLine')}</p> : <span className="review-spark-empty">—</span>
  const low = Math.min(...values.map(p => p.change_percent), 0)
  const high = Math.max(...values.map(p => p.change_percent), 0)
  const range = high - low || 1
  const y = (v: number) => 56 - (v - low) / range * 50
  const point = selected == null ? null : values[selected]
  return <div className={large ? 'review-chart-large' : 'review-spark'}>
    <svg viewBox="0 0 240 62" preserveAspectRatio="none" role={large ? 'img' : undefined} aria-label={large ? t('minute') : undefined} aria-hidden={!large}
      tabIndex={large ? 0 : undefined} className={muted ? 'text-muted-foreground' : marketSignTextClass(values[values.length - 1]?.change_percent)}
      onMouseMove={large ? e => { const rect = e.currentTarget.getBoundingClientRect(); setSelected(Math.min(values.length - 1, Math.max(0, Math.round((e.clientX - rect.left) / rect.width * (values.length - 1))))) } : undefined}
      onMouseLeave={() => setSelected(null)} onKeyDown={large ? e => { if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); setSelected(Math.max(0, Math.min(values.length - 1, (selected ?? 0) + (e.key === 'ArrowRight' ? 1 : -1)))) } } : undefined}>
      {large && <path d={`M0 ${y(0)}H240`} stroke="currentColor" strokeOpacity=".2" strokeDasharray="3 3" />}
      <polyline points={values.map((p, i) => `${i / (values.length - 1) * 240},${y(p.change_percent)}`).join(' ')} fill="none" stroke="currentColor" strokeWidth={large ? '.8' : '2.1'} vectorEffect="non-scaling-stroke" />
      {point && <circle cx={selected! / (values.length - 1) * 240} cy={y(point.change_percent)} r="1.5" fill="currentColor" />}
    </svg>
    {large && <div className="review-chart-caption"><span>{clock(point?.time ?? values[0].time)}</span><span>{point ? `${point.price.toFixed(2)} · ${pct(point.change_percent)}` : pct(values[values.length - 1]?.change_percent)}</span><span>{clock(values[values.length - 1]?.time)}</span></div>}
  </div>
}
export function Bars({ values, labels, label, compact = false, unit = '' }: { values: number[]; labels: string[]; label: string; compact?: boolean; unit?: string }) {
  const [selected, setSelected] = useState<number | null>(null)
  const max = Math.max(1, ...values.map(Math.abs))
  const negative = values.some(v => v < 0)
  const baseline = negative ? 34 : 66
  const scale = negative ? 29 : 60
  return <div className={compact ? 'review-bars compact' : 'review-bars'}>
    <svg viewBox="0 0 300 70" preserveAspectRatio="none" role="img" aria-label={label} tabIndex={0}
      onMouseMove={e => { const rect = e.currentTarget.getBoundingClientRect(); setSelected(Math.min(values.length - 1, Math.max(0, Math.floor((e.clientX - rect.left) / rect.width * values.length)))) }}
      onMouseLeave={() => setSelected(null)} onKeyDown={e => { if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); setSelected(Math.max(0, Math.min(values.length - 1, (selected ?? 0) + (e.key === 'ArrowRight' ? 1 : -1)))) } }}>
      <line x1="0" x2="300" y1={baseline} y2={baseline} stroke="currentColor" opacity=".12" />
      {values.map((v, i) => <rect key={i} x={i * 300 / values.length + 1} width={Math.max(.5, 300 / values.length - 2)}
        y={v >= 0 ? baseline - Math.abs(v) / max * scale : baseline} height={Math.max(.5, Math.abs(v) / max * scale)} rx=".8"
        fill="currentColor" className={marketSignTextClass(v)} opacity={selected === i ? 1 : .68}><title>{`${labels[i]} · ${v.toFixed(2)}${unit}`}</title></rect>)}
    </svg>
    {!compact && <div className="review-chart-caption"><span>{labels[0]}</span><span aria-live="polite">{selected != null ? `${labels[selected]} · ${values[selected]?.toFixed(2)}${unit}` : label}</span><span>{labels[labels.length - 1]}</span></div>}
  </div>
}
