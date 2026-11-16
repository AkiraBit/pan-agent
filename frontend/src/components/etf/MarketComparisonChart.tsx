import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { EtfHistory } from '@panwatch/api/etf'
import { Button } from '@panwatch/base-ui/components/ui/button'
import { marketSignTextClass } from '@/lib/market-colors'
import { numeric, signed } from './charts'
import { EtfChart, categoryAxis, chartBase, GRID_TOP, valueAxis, type ChartWindow } from './EtfChart'

const benchmarks = [
  { code: '000001', label: 'shComposite', color: '#bd830c', type: 'dashed' },
  { code: '000300', label: 'hs300', color: '#1595a5', type: 'dashed' },
  { code: '000688', label: 'star50', color: '#8a65cf', type: 'dotted' },
] as const

const groupColors = new Map([
  ['沪深300', '#2d6bd5'], ['中证1000', '#15958a'], ['中证500', '#d89636'], ['科创50', '#8361c2'],
  ['A500', '#cc5576'], ['创业板', '#528ba2'], ['上证50', '#ad6b39'],
])
const extraColors = ['#647a88', '#489853', '#ab9439', '#7276c3']
const cumulativeId = 'cumulative'
const aggregateId = 'aggregate'
const benchmarkId = (code: string) => `benchmark:${code}`
const groupId = (name: string) => `group:${name}`

export function MarketComparisonChart({ data, onDate }: { data: EtfHistory; onDate: (date: string) => void }) {
  const { t } = useTranslation('etf')
  const [zoom, setZoom] = useState<ChartWindow | null>(null)
  const [hidden, setHidden] = useState<Set<string>>(() => new Set())
  const points = data.series
  const dates = points.map(point => point.date)
  const visibleWindow: ChartWindow = zoom && zoom[1] < points.length ? zoom : [0, points.length - 1]
  const [first, last] = visibleWindow
  const visible = points.slice(first, last + 1)
  const unit = t('amountUnit')
  const base = visible.find(point => benchmarks.every(({ code }) => (point.benchmarks?.[code]?.close ?? 0) > 0))
  const groupNames = new Set(points.flatMap(point => Object.keys(point.net_by_index ?? {})))
  const groups = [...groupColors.keys()].filter(name => groupNames.delete(name)).concat([...groupNames].sort())
    .map((name, index) => ({ name, color: groupColors.get(name) ?? extraColors[index % extraColors.length] }))
  // Preserve reported net when a historical day has only a basket observation.
  const aggregate = points.map(point => Object.values(point.net_by_index ?? {}).some(group => group.net != null) ? null : point.net)
  const hasAggregate = aggregate.some(value => value != null)
  const cumulativeLabel = t(visible.some(point => point.net == null) ? 'knownCumulativeNet' : 'cumulativeNet')
  const offset = points.slice(0, first).reduce((sum, point) => sum + (point.net ?? 0), 0)
  let running = 0
  const cumulative = points.map(point => {
    if (point.net == null) return null
    running += point.net
    return running - offset
  })
  const percent = (value: number | null | undefined) => value == null ? '—' : `${signed(value, 2)}%`
  const money = (value: number | null | undefined, showSign = true) => value == null ? '—' : `${showSign ? signed(value) : numeric(value)} ${unit}`
  const indexReturn = (point: EtfHistory['series'][number], code: typeof benchmarks[number]['code']) => {
    const close = point.benchmarks?.[code]?.close
    const initial = base?.benchmarks?.[code]?.close
    return base && initial && close != null && point.date >= base.date ? (close / initial - 1) * 100 : null
  }
  const legend = [
    { id: cumulativeId, name: cumulativeLabel, className: 'etf-comparison-total-key', line: true },
    ...benchmarks.map(({ code, label, color }) => ({ id: benchmarkId(code), name: t(label), color, line: true, className: 'etf-comparison-dashed-key' })),
    ...groups.map(({ name, color }) => ({ id: groupId(name), name: `${name} ETF`, color, line: false })),
    ...(hasAggregate ? [{ id: aggregateId, name: t('unclassifiedNet'), className: 'etf-comparison-aggregate-key', line: false }] : []),
  ]
  const toggle = (id: string) => setHidden(previous => {
    const next = new Set(previous)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })

  return <section className="etf-card">
    <div className="etf-panel-heading">
      <h2>{t('netTrend')}</h2>
      {base && <span>{t('benchmarkBase', { date: base.date })}</span>}
    </div>
    <div className="etf-comparison-legend scrollbar">
      {legend.map(item => <Button key={item.id} variant="ghost" size="sm" aria-pressed={!hidden.has(item.id)} onClick={() => toggle(item.id)}>
        <i aria-hidden="true" className={`${item.line ? 'etf-comparison-line-key' : 'etf-comparison-bar-key'} ${'className' in item ? item.className : ''}`}
          style={'color' in item ? { color: item.color } : undefined} />
        {item.name}
      </Button>)}
      {!base && points.length > 0 && <span>{t(data.collecting ? 'benchmarkCollecting' : 'benchmarkUnavailable')}</span>}
    </div>
    {points.length ? <EtfChart
      className="etf-comparison-chart" label={t('benchmarkChart')} count={points.length} gridCount={2} showLatest guideOnLatest
      visibleWindow={visibleWindow} onWindowChange={setZoom} onActivate={index => onDate(points[index].date)}
      option={(colors, width) => {
        const compact = width < 660
        const right = compact ? 45 : 136
        const grid = { left: 53, right, outerBoundsMode: 'none' as const }
        const chart = chartBase(colors, grid.left, right)
        const axis = categoryAxis(dates, value => value, colors)
        const amountAxis = (name: string, gridIndex = 0, position: 'left' | 'right' = 'left') => ({
          ...valueAxis(colors, value => numeric(value, 0), position), gridIndex, name, nameGap: 8,
          nameTextStyle: { align: position, color: colors.text, fontSize: 11 },
        })
        const upperBars = groups.filter(({ name }) => !hidden.has(groupId(name))).map(({ name, color }) => ({
          id: groupId(name), name, type: 'bar' as const, stack: 'daily-net', stackStrategy: 'samesign' as const,
          barMaxWidth: 20, itemStyle: { color }, data: points.map(point => point.net_by_index?.[name]?.net ?? null),
        }))
        if (hasAggregate && !hidden.has(aggregateId)) upperBars.push({
          id: aggregateId, name: t('unclassifiedNet'), type: 'bar', stack: 'daily-net', stackStrategy: 'samesign',
          barMaxWidth: 20, itemStyle: { color: colors.volume }, data: aggregate,
        })
        return {
          ...chart,
          grid: [
            { ...grid, top: GRID_TOP, height: '62%' },
            { ...grid, top: '73%', bottom: 72 },
          ],
          axisPointer: { ...chart.axisPointer, link: [{ xAxisIndex: 'all' }] },
          xAxis: [0, 1].map(gridIndex => ({ ...axis, gridIndex,
            axisLabel: { ...axis.axisLabel, show: gridIndex === 1, interval: 'auto' as const,
              formatter: (value: string) => visible.length <= 7 ? value : value.slice(5).replace('-', '/'),
            },
          })),
          yAxis: [
            amountAxis(`${t('net')} · ${unit}`),
            { ...amountAxis(`${cumulativeLabel} · ${unit}`, 0, 'right'), show: !compact && !hidden.has(cumulativeId), scale: true },
            { ...valueAxis(colors, value => `${numeric(value)}%`, 'right'), gridIndex: 0,
              name: '%', nameGap: 8, nameTextStyle: { color: colors.text }, offset: compact ? 0 : 72,
              show: benchmarks.some(({ code }) => !hidden.has(benchmarkId(code))),
            },
            { ...amountAxis(`${t('turnover')} · ${unit}`, 1), min: 0, splitNumber: 2 },
          ],
          dataZoom: {
            type: 'slider', id: 'comparison-range', xAxisIndex: [0, 1], left: grid.left, right, bottom: 10, height: 24,
            startValue: first, endValue: last, rangeMode: ['value', 'value'], realtime: false, zoomLock: false,
            filterMode: 'filter', showDetail: false, showDataShadow: true, borderColor: colors.grid,
            backgroundColor: colors.grid, fillerColor: colors.volume,
            dataBackground: { lineStyle: { color: colors.index, opacity: .5 }, areaStyle: { color: colors.volume } },
            selectedDataBackground: { lineStyle: { color: colors.primary }, areaStyle: { color: colors.volume } },
            handleStyle: { color: colors.primary, borderColor: colors.primary }, textStyle: { color: colors.text },
          },
          series: [
            ...(!hidden.has(cumulativeId) ? [{
              id: cumulativeId, name: cumulativeLabel, type: 'line' as const, yAxisIndex: 1, data: cumulative,
              showSymbol: visible.filter(point => point.net != null).length < 3, symbolSize: 5, connectNulls: false, z: 5,
              lineStyle: { color: colors.foreground, width: 2.1 }, itemStyle: { color: colors.foreground },
            }] : []),
            ...benchmarks.filter(({ code }) => !hidden.has(benchmarkId(code))).map(({ code, label, color, type }) => ({
              id: benchmarkId(code), type: 'line' as const, name: t(label), yAxisIndex: 2,
              data: points.map(point => indexReturn(point, code)), connectNulls: false,
              showSymbol: visible.filter(point => indexReturn(point, code) != null).length < 3,
              symbolSize: 5, z: 4, lineStyle: { color, type, width: 1.5 }, itemStyle: { color },
            })),
            ...upperBars,
            { type: 'bar', name: t('turnover'), xAxisIndex: 1, yAxisIndex: 3, barMaxWidth: 20,
              itemStyle: { color: colors.primary, opacity: .65 }, data: points.map(point => point.amount) },
          ],
        }
      }}>
      {index => {
        if (index == null) return null
        const point = points[index]
        return <>
          <div className="etf-readout etf-comparison-readout">
            <span>{point.date}</span>
            <span>{t('net')} <b className={marketSignTextClass(point.net)}>{money(point.net)}</b></span>
            {!hidden.has(cumulativeId) && <span>{cumulativeLabel} <b className={marketSignTextClass(cumulative[index])}>{money(cumulative[index])}</b></span>}
            <span>{t('turnover')} <b>{money(point.amount, false)}</b></span>
            {benchmarks.filter(({ code }) => !hidden.has(benchmarkId(code))).map(({ code, label, color }) => {
              const close = point.benchmarks?.[code]?.close
              const change = indexReturn(point, code)
              return <span key={code} className="etf-comparison-quote">
                <i aria-hidden="true" style={{ backgroundColor: color }} />{t(label)}
                <b className={marketSignTextClass(change)}>{percent(change)}</b>
                {close != null && <small>{numeric(close, 2)} {t('indexPoints')}</small>}
              </span>
            })}
          </div>
          {groups.length > 0 && <div className="etf-readout etf-comparison-readout etf-comparison-groups">
            {groups.filter(({ name }) => !hidden.has(groupId(name))).map(({ name, color }) => {
              const group = point.net_by_index?.[name]
              return <span key={name} className="etf-comparison-quote">
                <i aria-hidden="true" style={{ backgroundColor: color }} />{name}
                <b className={marketSignTextClass(group?.net)}>{money(group?.net)}</b>
                {group && group.covered < group.expected && <small>{group.covered}/{group.expected}</small>}
              </span>
            })}
          </div>}
        </>
      }}
    </EtfChart> : <p className="etf-empty">{t('noHistory')}</p>}
  </section>
}
