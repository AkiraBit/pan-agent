import { useTranslation } from 'react-i18next'
import { marketSignTextClass } from '@/lib/market-colors'
import type { EtfBoard, EtfDay } from '@panwatch/api/etf'
import { EtfChart, categoryAxis, chartBase, dayTick, signedColor, valueAxis } from './EtfChart'

export const numeric = (value: number | null | undefined, digits = 1) => value == null || !Number.isFinite(value) ? '—' : value.toLocaleString(undefined, { maximumFractionDigits: digits })
export const signed = (value: number | null | undefined, digits = 1) => value == null ? '—' : `${value > 0 ? '+' : ''}${numeric(value, digits)}`

export function MinuteChart({ board }: { board: EtfBoard }) {
  const { t } = useTranslation('etf')
  const values = board.minutes ?? []
  const profile = new Map(board.profile ?? [])
  if (!values.length) return <p className="etf-empty">{t('empty')}</p>

  // A category axis keeps market minutes adjacent across the midday break.
  const labels = values.map(([time]) => time)
  const afternoon = labels.findIndex(time => time >= '13:00')
  const tick = (time: string, index: number) => {
    if (index === 0) return time === '09:31' ? '09:30' : time
    if (index === labels.length - 1) return time
    if (index === afternoon) return '11:30 / 13:00'
    return ''
  }
  const unit = t('amountUnit')
  const baseline = labels.map(time => profile.get(time) ?? null)
  return <EtfChart className="etf-minute-chart" label={t('minute')} count={values.length} showLatest option={colors => ({
    ...chartBase(colors, 8, 48),
    xAxis: categoryAxis(labels, tick, colors),
    yAxis: { ...valueAxis(colors, value => `${numeric(value)}${unit}`, 'right'), min: 0, splitLine: { show: true, lineStyle: { color: colors.grid } } },
    series: [
      { type: 'bar', stack: 'minute', barGap: '0%', barCategoryGap: '8%', itemStyle: { color: colors.volume },
        data: values.map(([, amount], i) => Math.min(amount, baseline[i] ?? amount)) },
      { type: 'bar', stack: 'minute', itemStyle: { color: colors.up },
        data: values.map(([, amount], i) => baseline[i] == null ? null : Math.max(0, amount - baseline[i]!)) },
      { type: 'line', data: baseline, connectNulls: false, showSymbol: false, silent: true, z: 3,
        lineStyle: { color: colors.baseline, type: 'dashed', width: 1.3 } },
    ],
  })}>
    {index => {
      if (index == null) return null
      const [time, amount] = values[index]
      const base = profile.get(time)
      const percent = base ? Math.round((amount / base - 1) * 100) : null
      return <div className="etf-chart-footer">
        <div className="etf-readout"><span>{time}</span><span>{t('minute')}</span><b>{numeric(amount, 2)} {unit}</b>{percent != null && <span className={marketSignTextClass(percent)}>{t(percent >= 0 ? 'more' : 'less', { value: Math.abs(percent) })}</span>}{time === '15:00' && <span>{t('auction')}</span>}</div>
        <div className="etf-legend"><span><i className="bg-market-up" />{t('excess')}</span><span><i className="etf-dashed" />{t('baseline')}</span></div>
      </div>
    }}
  </EtfChart>
}

export function FlowChart({ series, onDate }: { series: EtfDay[]; onDate: (day: string) => void }) {
  const { t } = useTranslation('etf')
  if (!series.length) return <p className="etf-empty">{t('empty')}</p>
  const hasIndex = series.some(row => row.hs300 != null)
  const limit = Math.max(1, ...series.map(row => Math.abs(row.net ?? 0))) * 1.1
  const labels = series.map(row => row.date)
  return <>
    <div className="etf-legend"><span><i className="bg-market-up" />{t('inflow')}</span><span><i className="bg-market-down" />{t('outflow')}</span>{hasIndex && <span><i className="etf-index-key" />{t('hs300')}</span>}<span><i className="etf-triangle-key" />{t('surge')}</span></div>
    <EtfChart className="etf-flow-chart" label={t('history')} count={series.length} onActivate={index => onDate(series[index].date)} option={colors => ({
      ...chartBase(colors, 54, hasIndex ? 58 : 18),
      xAxis: categoryAxis(labels, dayTick(labels.length), colors),
      yAxis: [
        { ...valueAxis(colors, value => signed(value, 0)), min: -limit, max: limit },
        ...(hasIndex ? [{ ...valueAxis(colors, value => numeric(value, 0), 'right'), scale: true }] : []),
      ],
      series: [
        { type: 'bar', barMaxWidth: 18, data: series.map(row => ({ value: row.net, itemStyle: { color: signedColor(colors, row.net), opacity: .75 } })) },
        ...(hasIndex ? [{ type: 'line' as const, yAxisIndex: 1, data: series.map(row => row.hs300), showSymbol: labels.length < 4,
          connectNulls: false, lineStyle: { color: colors.index, width: 1.5 }, itemStyle: { color: colors.index } }] : []),
        { type: 'scatter', silent: true, symbol: 'triangle', symbolRotate: 180, symbolSize: 8, itemStyle: { color: colors.surge },
          data: series.flatMap(row => (row.peak_window?.ratio ?? 0) >= 2 ? [[row.date, limit * .9]] : []) },
      ],
    })}>
      {index => {
        if (index == null) return null
        const selected = series[index]
        return <div className="etf-readout"><span>{selected.date}</span><b className={marketSignTextClass(selected.net)}>{signed(selected.net)} {t('amountUnit')}</b><span>{t('hs300')} {numeric(selected.hs300, 2)}</span></div>
      }}
    </EtfChart>
  </>
}
