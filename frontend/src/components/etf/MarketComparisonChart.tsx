import { useTranslation } from 'react-i18next'
import type { EtfHistory } from '@panwatch/api/etf'
import { marketSignTextClass } from '@/lib/market-colors'
import { numeric, signed } from './charts'
import { EtfChart, categoryAxis, chartBase, dayTick, GRID_TOP, signedColor, valueAxis } from './EtfChart'

const benchmarks = [
  { code: '000001', label: 'shComposite', color: '#5d73eb' },
  { code: '000300', label: 'hs300', color: '#1795a5' },
  { code: '000688', label: 'star50', color: '#b58022' },
] as const

export function MarketComparisonChart({ data, onDate }: { data: EtfHistory; onDate: (date: string) => void }) {
  const { t } = useTranslation('etf')
  const points = data.series
  const labels = points.map(point => point.date)
  const unit = t('amountUnit')
  const baseDate = data.benchmark_base_date
  const percent = (value: number | null | undefined) => value == null ? '—' : `${signed(value, 2)}%`
  const spansYears = labels[0]?.slice(0, 4) !== labels[labels.length - 1]?.slice(0, 4)

  return <section className="etf-card">
    <div className="etf-panel-heading">
      <h2>{t('benchmarkTrend')}</h2>
      {baseDate && <span>{t('benchmarkBase', { date: baseDate })}</span>}
    </div>
    <div className="etf-legend etf-benchmark-legend">
      {benchmarks.map(({ code, label, color }) => <span key={code}><i style={{ backgroundColor: color }} />{t(label)}</span>)}
      {!baseDate && points.length > 0 && <span>{t(data.collecting ? 'benchmarkCollecting' : 'benchmarkUnavailable')}</span>}
    </div>
    {points.length ? <EtfChart
      className="etf-comparison-chart" label={t('benchmarkChart')} count={points.length} gridCount={3} showLatest guideOnLatest
      onActivate={index => onDate(points[index].date)}
      option={colors => {
        const base = chartBase(colors, 58, 24)
        // Every pane uses the same trading-day categories and the same pixel bounds.
        const grid = { left: 58, right: 24, outerBoundsMode: 'none' as const }
        const axis = categoryAxis(labels, dayTick(labels.length, spansYears), colors)
        const rowAxis = (name: string, gridIndex: number) => ({
          ...valueAxis(colors, value => numeric(value, 0)),
          gridIndex, name, nameGap: 9, nameTextStyle: { align: 'left' as const, color: colors.text },
          splitNumber: 2,
        })
        return {
          ...base,
          grid: [
            { ...grid, top: GRID_TOP, height: '38%' },
            { ...grid, top: '51%', height: '19%' },
            { ...grid, top: '79%', bottom: 28 },
          ],
          axisPointer: { ...base.axisPointer, link: [{ xAxisIndex: 'all' }] },
          xAxis: [0, 1, 2].map(gridIndex => ({ ...axis, gridIndex,
            axisLabel: { ...axis.axisLabel, show: gridIndex === 2 },
          })),
          yAxis: [
            { ...valueAxis(colors, value => `${numeric(value, 1)}%`), gridIndex: 0 },
            rowAxis(`${t('net')} · ${unit}`, 1),
            { ...rowAxis(`${t('turnover')} · ${unit}`, 2), min: 0 },
          ],
          series: [
            ...benchmarks.map(({ code, label, color }) => ({
              type: 'line' as const, name: t(label), xAxisIndex: 0, yAxisIndex: 0,
              data: points.map(point => point.benchmarks?.[code]?.return_percent ?? null), connectNulls: false,
              showSymbol: points.filter(point => point.benchmarks?.[code]?.return_percent != null).length < 3,
              symbol: 'circle', symbolSize: 5, lineStyle: { color, width: 1.7 }, itemStyle: { color },
            })),
            { type: 'bar', name: t('net'), xAxisIndex: 1, yAxisIndex: 1, barMaxWidth: 18,
              data: points.map(point => ({ value: point.net, itemStyle: { color: signedColor(colors, point.net), opacity: .78 } })) },
            { type: 'bar', name: t('turnover'), xAxisIndex: 2, yAxisIndex: 2, barMaxWidth: 18,
              itemStyle: { color: colors.primary, opacity: .78 }, data: points.map(point => point.amount) },
          ],
        }
      }}>
      {index => {
        if (index == null) return null
        const point = points[index]
        return <div className="etf-readout etf-comparison-readout">
          <span>{point.date}</span>
          {benchmarks.map(({ code, label, color }) => {
            const indexPoint = point.benchmarks?.[code]
            const change = indexPoint?.return_percent
            return <span key={code} className="etf-comparison-quote">
              <i aria-hidden="true" style={{ backgroundColor: color }} />{t(label)}
              <b className={marketSignTextClass(change)}>{percent(change)}</b>
              {indexPoint && <small>{numeric(indexPoint.close, 2)} {t('indexPoints')}</small>}
            </span>
          })}
          <span>{t('net')} <b className={marketSignTextClass(point.net)}>{signed(point.net)} {unit}</b></span>
          <span>{t('turnover')} <b>{numeric(point.amount)} {unit}</b></span>
        </div>
      }}
    </EtfChart> : <p className="etf-empty">{t('noHistory')}</p>}
  </section>
}
