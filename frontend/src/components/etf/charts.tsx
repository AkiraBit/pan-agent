import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { marketSignTextClass } from '@/lib/market-colors'
import type { EtfBoard, EtfDay } from '@panwatch/api/etf'

export const numeric = (value: number | null | undefined, digits = 1) => value == null || !Number.isFinite(value) ? '—' : value.toLocaleString(undefined, { maximumFractionDigits: digits })
export const signed = (value: number | null | undefined, digits = 1) => value == null ? '—' : `${value > 0 ? '+' : ''}${numeric(value, digits)}`

export function useChartWidth() {
  const ref = useRef<SVGSVGElement>(null)
  const [width, setWidth] = useState(960)
  useEffect(() => {
    const svg = ref.current
    if (!svg || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(([entry]) => {
      if (entry.contentRect.width > 0) setWidth(entry.contentRect.width)
    })
    observer.observe(svg)
    return () => observer.disconnect()
  }, [])
  return { ref, width }
}

export function MinuteChart({ board }: { board: EtfBoard }) {
  const { t } = useTranslation('etf')
  const [hover, setHover] = useState<number | null>(null)
  const { ref, width } = useChartWidth()
  const values = board.minutes ?? []
  const profile = new Map(board.profile ?? [])
  if (!values.length) return <p className="etf-empty">{t('empty')}</p>
  const index = Math.min(values.length - 1, hover ?? values.length - 1)
  const point = values[index]
  const base = profile.get(point[0])
  const percent = base ? Math.round((point[1] / base - 1) * 100) : null
  const max = Math.max(1, ...values.map(v => v[1]), ...values.map(v => profile.get(v[0]) ?? 0)) * 1.06
  const x = (i: number) => 8 + i / Math.max(values.length - 1, 1) * (width - 16)
  const y = (v: number) => 272 - v / max * 240
  const baseline = values.map((v, i) => profile.has(v[0]) ? `${x(i)},${y(profile.get(v[0])!)}` : null).filter(Boolean).join(' ')
  return <>
    <svg className="etf-minute-chart" ref={ref} viewBox={`0 0 ${width} 306`} preserveAspectRatio="none" role="img" tabIndex={0} aria-label={t('minute')}
      onPointerMove={e => { const r = e.currentTarget.getBoundingClientRect(); setHover(Math.max(0, Math.min(values.length - 1, Math.round((e.clientX - r.left) / r.width * (values.length - 1))))) }}
      onPointerLeave={() => setHover(null)} onKeyDown={e => { if (['ArrowLeft', 'ArrowRight'].includes(e.key)) { e.preventDefault(); setHover(Math.max(0, Math.min(values.length - 1, index + (e.key === 'ArrowRight' ? 1 : -1)))) } }}>
      {[0, .5, 1].map(p => <line key={p} x1="8" x2={width - 8} y1={y(max * p)} y2={y(max * p)} className="etf-grid" />)}
      <text x={width - 10} y="28" textAnchor="end" className="etf-axis">{numeric(max, 0)}{t('amountUnit')}</text>
      {values.map(([time, value], i) => { const normal = profile.get(time); const floor = normal == null ? value : Math.min(normal, value); return <g key={time}>
        <rect x={x(i)} y={y(floor)} width={Math.max(1, (width - 16) / values.length - 1)} height={272 - y(floor)} className="etf-minute-bar" />
        {normal != null && value > normal && <rect x={x(i)} y={y(value)} width={Math.max(1, (width - 16) / values.length - 1)} height={y(normal) - y(value)} fill="currentColor" className="text-market-up" />}
      </g> })}
      <polyline points={baseline} fill="none" className="etf-baseline" strokeWidth="1.3" strokeDasharray="4 3" vectorEffect="non-scaling-stroke" />
      {hover != null && <line x1={x(index)} x2={x(index)} y1="30" y2="272" className="etf-guide" />}
      <text x="8" y="300" className="etf-axis">09:30</text><text x={width / 2} y="300" textAnchor="middle" className="etf-axis">11:30 / 13:00</text><text x={width - 8} y="300" textAnchor="end" className="etf-axis">15:00</text>
    </svg>
    <div className="etf-chart-footer"><div className="etf-readout"><span>{point[0]}</span><span>{t('minute')}</span><b>{numeric(point[1], 2)} {t('amountUnit')}</b>{percent != null && <span className={marketSignTextClass(percent)}>{t(percent >= 0 ? 'more' : 'less', { value: Math.abs(percent) })}</span>}{point[0] === '15:00' && <span>{t('auction')}</span>}</div>
      <div className="etf-legend"><span><i className="bg-market-up" />{t('excess')}</span><span><i className="etf-dashed" />{t('baseline')}</span></div></div>
  </>
}

export function FlowChart({ series, onDate }: { series: EtfDay[]; onDate: (day: string) => void }) {
  const { t } = useTranslation('etf')
  const [hover, setHover] = useState<number | null>(null)
  const { ref, width } = useChartWidth()
  if (!series.length) return <p className="etf-empty">{t('empty')}</p>
  const limit = Math.max(1, ...series.map(r => Math.abs(r.net ?? 0))) * 1.1
  const prices = series.flatMap(r => r.hs300 == null ? [] : [r.hs300])
  const low = Math.min(...prices), high = Math.max(...prices)
  const x = (i: number) => 34 + i / Math.max(1, series.length - 1) * (width - 76)
  const selected = hover == null ? null : series[hover]
  const pricePoints = series.map((r, i) => r.hs300 == null ? '' : `${x(i)},${218 - (r.hs300 - low) / (high - low || 1) * 180}`).filter(Boolean).join(' ')
  return <>
    <div className="etf-legend"><span><i className="bg-market-up" />{t('inflow')}</span><span><i className="bg-market-down" />{t('outflow')}</span><span><i className="etf-index-key" />{t('hs300')}</span><span><i className="etf-triangle-key" />{t('surge')}</span></div>
    <svg ref={ref} viewBox={`0 0 ${width} 270`} className="etf-flow-chart" preserveAspectRatio="none" role="img" aria-label={t('history')} tabIndex={0}
      onPointerMove={e => { const r = e.currentTarget.getBoundingClientRect(); setHover(Math.max(0, Math.min(series.length - 1, Math.round(((e.clientX - r.left) / r.width * width - 34) / (width - 76) * (series.length - 1))))) }} onPointerLeave={() => setHover(null)}
      onClick={() => { if (selected) onDate(selected.date) }} onKeyDown={e => { if (['ArrowLeft', 'ArrowRight'].includes(e.key)) { e.preventDefault(); setHover(Math.max(0, Math.min(series.length - 1, (hover ?? series.length - 1) + (e.key === 'ArrowRight' ? 1 : -1)))) } if (e.key === 'Enter' && selected) onDate(selected.date) }}>
      {[34, 132, 230].map(v => <line key={v} x1="24" x2={width - 30} y1={v} y2={v} className="etf-grid" />)}
      {series.map((r, i) => <g key={r.date}>{r.net != null && <rect x={x(i) - 3} y={r.net >= 0 ? 132 - r.net / limit * 100 : 132} width={Math.max(2, (width - 76) / series.length - 4)} height={Math.abs(r.net) / limit * 100} fill="currentColor" className={marketSignTextClass(r.net)} opacity=".75" />}{(r.peak_window?.ratio ?? 0) >= 2 && <path d={`M${x(i) - 4} 16h8l-4 6z`} className="etf-surge-mark" />}</g>)}
      {prices.length > 1 && <polyline points={pricePoints} fill="none" className="etf-index-line" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />}
      {selected && <line x1={x(hover!)} x2={x(hover!)} y1="25" y2="235" className="etf-guide" />}
      <text x={width - 28} y="36" textAnchor="end" className="etf-axis">+{numeric(limit, 0)}</text><text x={width - 28} y="130" textAnchor="end" className="etf-axis">0</text><text x={width - 28} y="230" textAnchor="end" className="etf-axis">-{numeric(limit, 0)}</text>
      {[...new Set([0, Math.floor(series.length / 2), series.length - 1])].map(i => <text key={i} x={x(i)} y="261" textAnchor="middle" className="etf-axis">{series[i].date.slice(5).replace('-', '/')}</text>)}
    </svg>
    {selected && <div className="etf-readout"><span>{selected.date}</span><b className={marketSignTextClass(selected.net)}>{signed(selected.net)} {t('amountUnit')}</b><span>{t('hs300')} {numeric(selected.hs300, 2)}</span></div>}
  </>
}
