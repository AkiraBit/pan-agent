import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { marketSignTextClass } from '@/lib/market-colors'
import { numeric, signed, useChartWidth } from './charts'

interface Point { date: string; value: number | null; secondary?: number | null; detail?: string }
interface Props {
  points: Point[]; label: string; unit: string; secondaryLabel?: string; bars?: boolean; market?: boolean;
  onDate?: (date: string) => void;
}

export function TrendChart({ points, label, unit, secondaryLabel, bars = false, market = false, onDate }: Props) {
  const { t } = useTranslation('etf')
  const { ref, width } = useChartWidth()
  const [hover, setHover] = useState<number | null>(null)
  const index = Math.max(0, Math.min(points.length - 1, hover ?? points.length - 1))
  const selected = points[index]
  const spansYears = new Set(points.map(point => point.date.slice(0, 4))).size > 1
  const values = points.flatMap(p => p.value == null ? [] : [p.value])
  const min = Math.min(0, ...values), max = Math.max(0, ...values)
  const span = max - min || 1
  const x = (i: number) => 38 + (points.length < 2 ? .5 : i / (points.length - 1)) * (width - 92)
  const y = (value: number) => 224 - (value - min) / span * 184
  const secondary = points.flatMap(p => p.secondary == null ? [] : [p.secondary])
  const low = Math.min(...secondary), high = Math.max(...secondary)
  const secondaryY = (value: number) => 224 - (value - low) / (high - low || 1) * 184
  const barWidth = Math.max(1, Math.min(18, (width - 92) / Math.max(points.length, 1) * .65))
  const path = (field: 'value' | 'secondary', project: (n: number) => number) => {
    let continuous = false
    return points.map((p, i) => {
      const value = p[field]
      if (value == null) { continuous = false; return '' }
      const command = continuous ? 'L' : 'M'
      continuous = true
      return `${command}${x(i)},${project(value)}`
    }).join(' ')
  }
  const pointerIndex = (clientX: number, rect: DOMRect) => Math.max(0, Math.min(points.length - 1,
    Math.round(((clientX - rect.left) / rect.width * width - 38) / (width - 92) * (points.length - 1))))
  if (!points.length) return <p className="etf-empty">{t('noHistory')}</p>
  return <>
    <div className="etf-legend"><span><i className={market ? 'bg-market-up' : 'etf-primary-key'} />{label} · {unit}</span>{secondaryLabel && <span><i className="etf-index-key" />{secondaryLabel}</span>}</div>
    <svg ref={ref} viewBox={`0 0 ${width} 270`} className="etf-trend-chart" role="img" aria-label={label} tabIndex={0}
      onPointerMove={event => setHover(pointerIndex(event.clientX, event.currentTarget.getBoundingClientRect()))}
      onPointerLeave={() => setHover(null)}
      onClick={event => { const point = points[pointerIndex(event.clientX, event.currentTarget.getBoundingClientRect())]; if (point) onDate?.(point.date) }}
      onKeyDown={event => {
        if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
          event.preventDefault(); setHover(Math.max(0, Math.min(points.length - 1, index + (event.key === 'ArrowLeft' ? -1 : 1))))
        }
        if (event.key === 'Enter' && selected) onDate?.(selected.date)
      }}>
      {[40, 132, 224].map(value => <line key={value} x1="28" x2={width - 42} y1={value} y2={value} className="etf-grid" />)}
      {values.length > 0 && <>
        <line x1="28" x2={width - 42} y1={y(0)} y2={y(0)} className="etf-grid" />
        {bars ? points.map((point, i) => point.value == null ? null : <rect key={point.date}
          x={x(i) - barWidth / 2} y={Math.min(y(0), y(point.value))} width={barWidth} height={Math.max(.6, Math.abs(y(point.value) - y(0)))}
          fill="currentColor" className={market ? marketSignTextClass(point.value) : 'etf-primary-color'} opacity=".78" />)
          : <path d={path('value', y)} fill="none" className="etf-primary-line" strokeWidth="2" vectorEffect="non-scaling-stroke" />}
        {!bars && points.map((point, i) => point.value == null ? null : <circle key={point.date} cx={x(i)} cy={y(point.value)} r={points.length < 30 ? 3 : 1.4} className="etf-primary-fill" />)}
        <text x="27" y="32" className="etf-axis">{numeric(max, 1)}</text>
        <text x="27" y="241" className="etf-axis">{numeric(min, 1)}</text>
      </>}
      {secondary.length > 0 && <><path d={path('secondary', secondaryY)} fill="none" className="etf-index-line" strokeWidth="1.4" vectorEffect="non-scaling-stroke" />
        <text x={width - 7} y="32" textAnchor="end" className="etf-axis">{numeric(high, 0)}</text>
        <text x={width - 7} y="241" textAnchor="end" className="etf-axis">{numeric(low, 0)}</text></>}
      {selected && <line x1={x(index)} x2={x(index)} y1="35" y2="228" className="etf-guide" />}
      {[...new Set([0, Math.floor(points.length / 2), points.length - 1])].filter(i => points[i]).map(i =>
        <text key={i} x={x(i)} y="263" textAnchor="middle" className="etf-axis">{points.length < 4 ? points[i].date : spansYears ? points[i].date.slice(0, 7) : points[i].date.slice(5).replace('-', '/')}</text>)}
    </svg>
    {selected && <div className="etf-readout"><span>{selected.date}</span><span>{label}</span><b className={market ? marketSignTextClass(selected.value) : ''}>{market ? signed(selected.value) : numeric(selected.value)} {unit}</b>
      {secondaryLabel && <span>{secondaryLabel} {numeric(selected.secondary, 2)}</span>}{selected.detail && <span>{selected.detail}</span>}</div>}
  </>
}
