import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import { init, use, type ComposeOption, type EChartsType } from 'echarts/core'
import { BarChart, LineChart, type BarSeriesOption, type LineSeriesOption } from 'echarts/charts'
import { DataZoomSliderComponent, GridComponent, MarkLineComponent, TooltipComponent, type DataZoomComponentOption, type GridComponentOption, type TooltipComponentOption } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useTranslation } from 'react-i18next'
import type { EtfIntraday, EtfTurnoverBaseline } from '@panwatch/api/etf'
import { CNY_PER_YI, ETF_SESSION_MINUTES as MINUTES, etfIntradayMove, minuteTurnoverFromCumulative } from './session'
import { etfPriceColor, priceInstrumentKey, type EtfChartPrice } from './price-palette'
import './intraday-chart.css'

use([CanvasRenderer, GridComponent, TooltipComponent, DataZoomSliderComponent, MarkLineComponent, BarChart, LineChart])

type Options = ComposeOption<BarSeriesOption | LineSeriesOption | GridComponentOption | TooltipComponentOption | DataZoomComponentOption>

export function IntradayChart({ data, turnoverBaseline, prices }: {
  data: EtfIntraday
  turnoverBaseline?: EtfTurnoverBaseline | null
  prices: EtfChartPrice[]
}) {
  const { t, i18n } = useTranslation('etf')
  const host = useRef<HTMLDivElement>(null)
  const chart = useRef<EChartsType | null>(null)
  const [focus, setFocus] = useState<number | null>(null)
  const indexed = useMemo(() => new Map(data.points.map(point => [point.minute, point])), [data.points])
  const benchmark = useMemo(() => minuteTurnoverFromCumulative(turnoverBaseline?.cumulative_cny), [turnoverBaseline])
  const moves = useMemo(() => prices.flatMap(price => {
    const move = etfIntradayMove(price.closes)
    return move ? [{ instrument: price.instrument, colorIndex: price.colorIndex, ...move }] : []
  }), [prices])
  const lastTurnover = data.points.reduce((last, point) => point.turnover_cny != null ? point.minute : last, '')
  const number = useMemo(() => new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 2 }), [i18n.language])
  const movePercent = useMemo(() => new Intl.NumberFormat(i18n.language, {
    style: 'percent', minimumFractionDigits: 2, maximumFractionDigits: 2, signDisplay: 'exceptZero',
  }), [i18n.language])
  const percent = useMemo(() => new Intl.NumberFormat(i18n.language, { style: 'percent', maximumFractionDigits: 1 }), [i18n.language])
  const amount = (value: number) => `${number.format(value / CNY_PER_YI)} ${t('amountUnit')}`
  const minuteAverage = turnoverBaseline ? t('minuteAverage', { count: turnoverBaseline.sessions }) : undefined
  const describe = (index: number) => {
    const minute = MINUTES[index]
    const point = indexed.get(minute)
    const actual = point?.turnover_cny
    const usual = minute <= lastTurnover ? benchmark[index] : null
    const change = actual != null && usual != null && usual > 0 && point?.etf_count === data.symbols.length
      ? actual / usual - 1 : null
    return [
      minute,
      `${t('turnover')}  ${actual == null ? '—' : amount(actual)}`,
      ...(usual == null ? [] : [`${minuteAverage}  ${amount(usual)}`]),
      ...(change == null ? [] : [Math.abs(change) < .0005 ? t('flat')
        : t(change > 0 ? 'aboveAverage' : 'belowAverage', { change: percent.format(Math.abs(change)) })]),
      `${t('index')}  ${point?.index_close == null ? '—' : number.format(point.index_close)}`,
      ...moves.map(({ instrument, baseMinute, values }) => {
        const move = values[index]
        return `${instrument.name}  ${move == null ? '—' : t('priceMoveFrom', { time: baseMinute, change: movePercent.format(move) })}`
      }),
      t('pointCoverage', { loaded: point?.etf_count ?? 0, total: data.symbols.length }),
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
    const baseline = data.previous_close
    const indexValues = data.points.flatMap(point => point.index_close == null ? [] : [point.index_close])
    if (baseline != null) indexValues.push(baseline)
    const low = Math.min(...indexValues)
    const high = Math.max(...indexValues)
    const padding = Math.max(2, (high - low) * .08)
    const turnover = t('turnover')
    const index = t('index')

    return {
      animation: false,
      textStyle: { fontFamily: style.fontFamily },
      grid: { left: 45, right: 55, top: 14, bottom: 66 },
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
      xAxis: {
        type: 'category', data: MINUTES, boundaryGap: true,
        axisTick: { show: false }, axisLine: { lineStyle: { color: border } },
        axisLabel: { color: muted, fontSize: 11, hideOverlap: true, showMinLabel: true, showMaxLabel: true },
      },
      yAxis: [
        {
          type: 'value', min: 0, splitNumber: 4, show: data.etf_count > 0,
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
      ],
      dataZoom: [{
        id: 'minute-window', type: 'slider', height: 25, bottom: 10, left: 45, right: 55, minValueSpan: 8,
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
            return point.etf_count === data.symbols.length
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
            if (point?.turnover_cny == null || point.etf_count !== data.symbols.length || usual == null || point.turnover_cny <= usual) return null
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
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
    return () => { observer.disconnect(); theme.disconnect(); instance.dispose(); chart.current = null }
  }, [])
  useLayoutEffect(() => {
    if (chart.current && host.current) chart.current.setOption(settings.current(host.current), { replaceMerge: ['series'] })
  }, [data, turnoverBaseline, moves, i18n.language, t])

  return <>
    <div
      ref={host}
      role="img"
      tabIndex={0}
      aria-label={t('chartLabel')}
      className="h-[330px] w-full rounded-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring sm:h-[430px] xl:h-[min(54vh,540px)]"
      onKeyDown={event => {
        if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
        event.preventDefault()
        const last = data.points.length - 1
        const next = Math.min(last, Math.max(0, (focus ?? last) + (event.key === 'ArrowLeft' ? -1 : 1)))
        const point = data.points[next]
        if (!point) return
        setFocus(next)
        chart.current?.dispatchAction({ type: 'showTip', seriesIndex: point.turnover_cny != null ? 0 : 1, dataIndex: MINUTES.indexOf(point.minute) })
      }}
      onBlur={() => { setFocus(null); chart.current?.dispatchAction({ type: 'hideTip' }) }}
    />
    <span className="sr-only" aria-live="polite">{focus == null || !data.points[focus] ? '' : describe(MINUTES.indexOf(data.points[focus].minute))}</span>
  </>
}
