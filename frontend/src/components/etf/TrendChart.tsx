import { useTranslation } from 'react-i18next'
import { marketSignTextClass } from '@/lib/market-colors'
import { numeric, signed } from './charts'
import { EtfChart, categoryAxis, chartBase, dayTick, signedColor, valueAxis } from './EtfChart'

interface Point { date: string; value: number | null; secondary?: number | null; detail?: string }
interface Props {
  points: Point[]; label: string; unit: string; secondaryLabel?: string; bars?: boolean; market?: boolean;
  onDate?: (date: string) => void;
}

export function TrendChart({ points, label, unit, secondaryLabel, bars = false, market = false, onDate }: Props) {
  const { t } = useTranslation('etf')
  if (!points.length) return <p className="etf-empty">{t('noHistory')}</p>
  const labels = points.map(point => point.date)
  const spansYears = labels[0].slice(0, 4) !== labels[labels.length - 1].slice(0, 4)
  const hasSecondary = Boolean(secondaryLabel && points.some(point => point.secondary != null))
  return <>
    <div className="etf-legend"><span><i className={market && bars ? 'bg-market-up' : 'etf-primary-key'} />{label} · {unit}</span>{hasSecondary && <span><i className="etf-index-key" />{secondaryLabel}</span>}</div>
    <EtfChart className="etf-trend-chart" label={label} count={points.length} showLatest guideOnLatest
      onActivate={onDate ? index => onDate(points[index].date) : undefined}
      option={colors => ({
        ...chartBase(colors, 54, hasSecondary ? 58 : 18),
        xAxis: categoryAxis(labels, dayTick(labels.length, spansYears), colors),
        yAxis: [
          valueAxis(colors, value => numeric(value)),
          ...(hasSecondary ? [{ ...valueAxis(colors, value => numeric(value, 0), 'right'), scale: true }] : []),
        ],
        series: [
          bars
            ? { type: 'bar', barMaxWidth: 18, data: points.map(point => ({ value: point.value, itemStyle: { color: market ? signedColor(colors, point.value) : colors.primary, opacity: .78 } })) }
            : { type: 'line', data: points.map(point => point.value), connectNulls: false, symbol: 'circle',
              symbolSize: points.length < 30 ? 6 : 3, lineStyle: { color: colors.primary, width: 2 }, itemStyle: { color: colors.primary } },
          ...(hasSecondary ? [{ type: 'line' as const, yAxisIndex: 1, data: points.map(point => point.secondary ?? null),
            connectNulls: false, showSymbol: points.length < 4, lineStyle: { color: colors.index, width: 1.4 }, itemStyle: { color: colors.index } }] : []),
        ],
      })}>
      {index => {
        if (index == null) return null
        const selected = points[index]
        return <div className="etf-readout"><span>{selected.date}</span><span>{label}</span><b className={market ? marketSignTextClass(selected.value) : ''}>{market ? signed(selected.value) : numeric(selected.value)} {unit}</b>
          {secondaryLabel && <span>{secondaryLabel} {numeric(selected.secondary, 2)}</span>}{selected.detail && <span>{selected.detail}</span>}</div>
      }}
    </EtfChart>
  </>
}
