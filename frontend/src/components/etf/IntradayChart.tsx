import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import { init, use, type ComposeOption, type EChartsType } from 'echarts/core'
import { BarChart, LineChart, type BarSeriesOption, type LineSeriesOption } from 'echarts/charts'
import { AxisPointerComponent, DataZoomSliderComponent, GridComponent, MarkLineComponent, TooltipComponent, type AxisPointerComponentOption, type DataZoomComponentOption, type GridComponentOption, type TooltipComponentOption } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useTranslation } from 'react-i18next'
import type { EtfIntraday, EtfMarketStats, EtfMinutePoint, EtfTurnoverBaseline } from '@panwatch/api/etf'
import { CNY_PER_YI, ETF_SESSION_MINUTES as MINUTES, etfIntradayMove, minuteTurnoverFromCumulative } from './session'
import { etfPriceColor, priceInstrumentKey, type EtfChartPrice } from './price-palette'
import './intraday-chart.css'

use([CanvasRenderer, GridComponent, TooltipComponent, AxisPointerComponent, DataZoomSliderComponent, MarkLineComponent, BarChart, LineChart])

type Options = ComposeOption<BarSeriesOption | LineSeriesOption | GridComponentOption | TooltipComponentOption | DataZoomComponentOption | AxisPointerComponentOption>
const EMPTY_POINTS: EtfMinutePoint[] = []
const GRID_INSETS = { left: 45, right: 55 }

export function IntradayChart({ data, turnoverBaseline, prices, breadth, breadthFailed }: {
  data?: EtfIntraday
  turnoverBaseline?: EtfTurnoverBaseline | null
  prices: EtfChartPrice[]
  breadth?: EtfMarketStats['breadth']
  breadthFailed?: boolean
}) {
  const { t, i18n } = useTranslation('etf')
  const host = useRef<HTMLDivElement>(null)
  const chart = useRef<EChartsType | null>(null)
  const [focus, setFocus] = useState<number | null>(null)
  const points = data?.points ?? EMPTY_POINTS
  const main = points.length > 0
  const sampleCount = data?.symbols.length ?? 0
  const indexed = useMemo(() => new Map(points.map(point => [point.minute, point])), [points])
  const benchmark = useMemo(() => minuteTurnoverFromCumulative(turnoverBaseline?.cumulative_cny), [turnoverBaseline])
  const moves = useMemo(() => prices.flatMap(price => {
    const move = etfIntradayMove(price.closes)
    return move ? [{ instrument: price.instrument, colorIndex: price.colorIndex, ...move }] : []
  }), [prices])
  const lastTurnover = points.reduce((last, point) => point.turnover_cny != null ? point.minute : last, '')
  const lastBreadth = Object.keys(breadth?.points ?? {}).sort().pop()
  const gaps = MINUTES.filter(minute => breadth?.through && minute <= breadth.through && !breadth.points[minute]).length
  const number = useMemo(() => new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 2 }), [i18n.language])
  const movePercent = useMemo(() => new Intl.NumberFormat(i18n.language, {
    style: 'percent', minimumFractionDigits: 2, maximumFractionDigits: 2, signDisplay: 'exceptZero',
  }), [i18n.language])
  const percent = useMemo(() => new Intl.NumberFormat(i18n.language, { style: 'percent', maximumFractionDigits: 1 }), [i18n.language])
  const amount = (value: number) => `${number.format(value / CNY_PER_YI)} ${t('amountUnit')}`
  const minuteAverage = turnoverBaseline ? t('minuteAverage', { count: turnoverBaseline.sessions }) : undefined
  const breadthText = (point: { up: number; down: number; flat: number }) => t('breadthCounts', {
    up: number.format(point.up), down: number.format(point.down), flat: number.format(point.flat),
  })
  const describe = (index: number) => {
    const minute = MINUTES[index]
    const point = indexed.get(minute)
    const actual = point?.turnover_cny
    const usual = minute <= lastTurnover ? benchmark[index] : null
    const change = actual != null && usual != null && usual > 0 && point?.etf_count === sampleCount
      ? actual / usual - 1 : null
    const counts = breadth?.points[minute]
    return [
      minute,
      ...(main ? [`${t('turnover')}  ${actual == null ? '—' : amount(actual)}`,
      ...(usual == null ? [] : [`${minuteAverage}  ${amount(usual)}`]),
      ...(change == null ? [] : [Math.abs(change) < .0005 ? t('flat')
        : t(change > 0 ? 'aboveAverage' : 'belowAverage', { change: percent.format(Math.abs(change)) })]),
      `${t('index')}  ${point?.index_close == null ? '—' : number.format(point.index_close)}`,
      ...moves.map(({ instrument, baseMinute, values }) => {
        const move = values[index]
        return `${instrument.name}  ${move == null ? '—' : t('priceMoveFrom', { time: baseMinute, change: movePercent.format(move) })}`
      }),
      t('pointCoverage', { loaded: point?.etf_count ?? 0, total: sampleCount })] : []),
      ...(counts ? [breadthText(counts)] : breadth?.through && minute <= breadth.through
        ? [`${t('breadth')} · ${t('breadthMissing')}`] : []),
    ].join('\n')
  }
  const buildOptions = (node: HTMLDivElement): Options => {
    const style = getComputedStyle(node)
    const dark = document.documentElement.classList.contains('dark')
    const color = (token: string) => `hsl(${style.getPropertyValue(token).trim()})`
    const plotColor = (part: string) => style.getPropertyValue(`--etf-${part}`).trim()
    const primary = plotColor('turnover-bar')
    const partial = plotColor('partial-bar')
    const excess = plotColor('excess-bar')
    const usual = plotColor('usual-line')
    const indexColor = plotColor('index-line')
    const muted = color('--secondary-foreground')
    const border = color('--border')
    const baseline = data?.previous_close
    const indexValues = points.flatMap(point => point.index_close == null ? [] : [point.index_close])
    if (baseline != null) indexValues.push(baseline)
    const low = Math.min(...indexValues)
    const high = Math.max(...indexValues)
    const padding = Math.max(2, (high - low) * .08)
    const turnover = t('turnover')
    const index = t('index')
    const breadthLimit = Math.max(1000, ...Object.values(breadth?.points ?? {}).map(({ up, down }) =>
      Math.ceil(Math.abs(up - down) / 1000) * 1000))

    return {
      animation: false,
      textStyle: { fontFamily: style.fontFamily },
      grid: [
        { ...GRID_INSETS, outerBoundsMode: 'none', top: 14, ...(main ? { bottom: 214 } : { height: 0 }) },
        { ...GRID_INSETS, outerBoundsMode: 'none', bottom: 65, height: 105 },
      ],
      axisPointer: { link: [{ xAxisIndex: [0, 1] }] },
      tooltip: {
        trigger: 'axis',
        confine: true,
        renderMode: 'richText',
        backgroundColor: color('--card'),
        borderColor: border,
        textStyle: { color: color('--foreground'), fontSize: 12 },
        axisPointer: { type: 'line', lineStyle: { color: muted, type: 'dashed' } },
        formatter: params => {
          const first = Array.isArray(params) ? params[0] : params
          return first ? describe(first.dataIndex) : ''
        },
      },
      xAxis: [0, 1].map(gridIndex => ({
        gridIndex, show: gridIndex === 1 || main, type: 'category' as const, data: MINUTES, boundaryGap: true,
        axisTick: { show: false }, axisLine: { onZero: false, lineStyle: { color: border } },
        axisLabel: { show: gridIndex === 1, color: muted, fontSize: 11, hideOverlap: true, showMinLabel: true, showMaxLabel: true },
      })),
      yAxis: [
        {
          type: 'value', min: 0, splitNumber: 4, show: (data?.etf_count ?? 0) > 0,
          axisLabel: { color: muted, fontSize: 11, formatter: value => number.format(Number(value)) },
          splitLine: { lineStyle: { color: border } },
        },
        {
          type: 'value', position: 'right', scale: true, splitNumber: 4,
          show: indexValues.length > 0,
          ...(indexValues.length ? { min: Math.floor((low - padding) / 5) * 5, max: Math.ceil((high + padding) / 5) * 5 } : {}),
          axisLabel: { color: muted, fontSize: 11, formatter: value => number.format(Number(value)) },
          splitLine: { show: false },
        },
        {
          type: 'value', scale: true, show: false,
          min: ({ min, max }) => Math.min(0, min) - Math.max(.0005, (max - min) * .08),
          max: ({ min, max }) => Math.max(0, max) + Math.max(.0005, (max - min) * .08),
          axisPointer: { show: false },
          splitLine: { show: false },
        },
        {
          type: 'value', gridIndex: 1, min: -breadthLimit, max: breadthLimit, interval: breadthLimit,
          show: !!lastBreadth,
          axisLabel: { color: muted, fontSize: 11, formatter: value => number.format(Number(value)) },
          splitLine: { lineStyle: { color: border } },
        },
      ],
      dataZoom: [{
        id: 'minute-window', type: 'slider', xAxisIndex: [0, 1], ...GRID_INSETS, height: 25, bottom: 10, minValueSpan: 8,
        showDetail: false, borderColor: border, backgroundColor: color('--muted'),
        fillerColor: dark ? 'rgba(118,169,255,.19)' : 'rgba(57,121,237,.14)',
        dataBackground: { lineStyle: { color: partial }, areaStyle: { color: partial, opacity: .2 } },
        selectedDataBackground: { lineStyle: { color: primary }, areaStyle: { color: primary, opacity: .18 } },
        handleStyle: { color: color('--card'), borderColor: primary },
        brushSelect: false,
      }],
      series: [
        {
          id: 'funds', name: turnover, type: 'bar', yAxisIndex: 0, stack: 'turnover',
          barMaxWidth: 10,
          itemStyle: { color: primary },
          data: MINUTES.map((minute, index) => {
            const point = indexed.get(minute)
            if (point?.turnover_cny == null) return null
            const value = point.turnover_cny / CNY_PER_YI
            const usual = benchmark[index]
            return point.etf_count === sampleCount
              ? (usual == null ? value : Math.min(value, usual / CNY_PER_YI))
              : { value, itemStyle: { color: partial } }
          }),
        },
        {
          id: 'index', name: index, type: 'line', yAxisIndex: 1, z: 4,
          showSymbol: false, connectNulls: false, lineStyle: { color: indexColor, width: 1.75 }, itemStyle: { color: indexColor },
          data: MINUTES.map(minute => indexed.get(minute)?.index_close ?? null),
          markLine: {
            silent: true, symbol: ['none', 'none'],
            lineStyle: { color: muted, type: 'dashed', opacity: .75 },
            label: { color: muted, position: 'insideEndTop', fontSize: 11 },
            data: baseline == null ? [] : [{ yAxis: baseline, label: { formatter: `${t('previousClose')} ${number.format(baseline)}` } }],
          },
        },
        {
          id: 'turnover-excess', name: t('excessMinute'), type: 'bar', yAxisIndex: 0, stack: 'turnover',
          barMaxWidth: 10,
          itemStyle: { color: excess },
          data: MINUTES.map((minute, index) => {
            const point = indexed.get(minute)
            const usual = benchmark[index]
            if (point?.turnover_cny == null || point.etf_count !== sampleCount || usual == null || point.turnover_cny <= usual) return null
            return (point.turnover_cny - usual) / CNY_PER_YI
          }),
        },
        {
          id: 'turnover-usual', name: minuteAverage, type: 'line', yAxisIndex: 0, z: 5,
          showSymbol: false, connectNulls: false, lineStyle: { color: usual, width: 1.5, type: 'dashed' },
          data: MINUTES.map((minute, index) => {
            const value = benchmark[index]
            return minute <= lastTurnover && value != null ? value / CNY_PER_YI : null
          }),
        },
        ...moves.map(({ instrument, values, colorIndex }): LineSeriesOption => {
          const priceColor = etfPriceColor(colorIndex, dark)
          return {
            id: `overlay-${priceInstrumentKey(instrument)}`, name: instrument.name, type: 'line', yAxisIndex: 2, z: 6,
            showSymbol: false, connectNulls: false, lineStyle: { color: priceColor, width: 2 },
            itemStyle: { color: priceColor },
            data: values,
          }
        }),
        {
          id: 'breadth-net', type: 'bar', xAxisIndex: 1, yAxisIndex: 3, barMaxWidth: 9,
          name: t('breadthNet'), data: MINUTES.map(minute => {
            const point = breadth?.points[minute]
            if (!point) return null
            const value = point.up - point.down
            return { value, itemStyle: { color: color(value >= 0 ? '--market-up' : '--market-down') } }
          }),
        },
        {
          id: 'breadth-gaps', type: 'line', xAxisIndex: 1, yAxisIndex: 3, silent: true,
          symbol: 'rect', symbolSize: [3, 3], showAllSymbol: true, lineStyle: { opacity: 0 }, itemStyle: { color: muted, opacity: .45 },
          data: MINUTES.map(minute => breadth?.through && minute <= breadth.through && !breadth.points[minute] ? 0 : null),
        },
        {
          // An invisible anchor keeps the shared tooltip reachable at missing minutes.
          id: 'breadth-tooltip', type: 'line', xAxisIndex: 1, yAxisIndex: 3, silent: true,
          showSymbol: false, lineStyle: { opacity: 0 }, emphasis: { disabled: true },
          data: MINUTES.map(() => 0),
        },
      ],
    }
  }

  const settings = useRef(buildOptions)
  settings.current = buildOptions
  useLayoutEffect(() => {
    const node = host.current
    if (!node) return
    const instance = init(node)
    chart.current = instance
    const repaint = () => instance.setOption(settings.current(node), { replaceMerge: ['series'] })
    repaint()
    const observer = new ResizeObserver(() => instance.resize())
    observer.observe(node)
    const theme = new MutationObserver(repaint)
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'data-market-color-scheme'] })
    return () => { observer.disconnect(); theme.disconnect(); instance.dispose(); chart.current = null }
  }, [])
  useLayoutEffect(() => {
    if (chart.current && host.current) chart.current.setOption(settings.current(host.current), { replaceMerge: ['series'] })
  }, [data, turnoverBaseline, moves, breadth, i18n.language, t])

  const through = breadth?.through
  const lastMinute = [points[points.length - 1]?.minute ?? '', through ?? ''].sort()[1]
  const latestCounts = lastBreadth ? breadth?.points[lastBreadth] : undefined
  return <div className="relative">
    <div className="pointer-events-none absolute inset-x-2 bottom-[177px] z-10 flex items-baseline justify-between gap-2 border-t border-border/70 px-1 pt-2 text-[11px] text-secondary-foreground sm:inset-x-3">
      <div className="flex min-w-0 items-baseline gap-2">
        <span className="shrink-0 font-semibold text-foreground">{t('breadth')}</span>
        <span className="hidden truncate md:inline">{t('breadthNet')}</span>
      </div>
      <div className="flex shrink-0 items-baseline gap-2 tabular-nums">
        {latestCounts && <span className="hidden lg:inline">{lastBreadth} · {breadthText(latestCounts)}</span>}
        {!lastBreadth ? <span>{t(through ? 'breadthMissing' : breadthFailed ? 'flowUnavailable' : breadth ? 'breadthNotDue' : 'loading')}</span>
          : gaps > 0 && <span>{t('breadthGaps', { count: gaps })}</span>}
      </div>
    </div>
    <div
      ref={host}
      role="img"
      tabIndex={0}
      aria-label={main ? `${t('chartLabel')} · ${t('breadth')}` : t('breadth')}
      className={`w-full rounded-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring ${main ? 'h-[478px] sm:h-[578px] xl:h-[min(54vh+148px,688px)]' : 'h-[214px]'}`}
      onKeyDown={event => {
        if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
        event.preventDefault()
        const last = MINUTES.indexOf(lastMinute)
        const next = Math.min(last, Math.max(0, (focus ?? last) + (event.key === 'ArrowLeft' ? -1 : 1)))
        if (last < 0) return
        setFocus(next)
        const instance = chart.current
        const series = instance?.getOption().series as ({ id?: string } | undefined)[] | undefined
        const seriesIndex = series?.findIndex(item => item?.id === 'breadth-tooltip') ?? -1
        if (seriesIndex !== -1) instance?.dispatchAction({ type: 'showTip', seriesIndex, dataIndex: next })
      }}
      onBlur={() => { setFocus(null); chart.current?.dispatchAction({ type: 'hideTip' }) }}
    />
    <span className="sr-only" aria-live="polite">{focus == null ? '' : describe(focus)}</span>
  </div>
}
