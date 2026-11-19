import { useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { init, use, type ComposeOption, type EChartsType } from 'echarts/core'
import { BarChart, LineChart, type BarSeriesOption, type LineSeriesOption } from 'echarts/charts'
import { AxisPointerComponent, BrushComponent, DataZoomSliderComponent, GridComponent, MarkAreaComponent, MarkLineComponent, TooltipComponent,
  type AxisPointerComponentOption, type BrushComponentOption, type DataZoomComponentOption, type GridComponentOption, type TooltipComponentOption } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useTranslation } from 'react-i18next'
import type { EtfIntraday, EtfMarketStats, EtfMinutePoint, EtfTurnoverBaseline } from '@panwatch/api/etf'
import { CNY_PER_YI, ETF_SESSION_MINUTES as MINUTES, etfIntradayMove, minuteTurnoverFromCumulative } from './session'
import { etfPriceColor, priceInstrumentKey, type EtfChartPrice } from './price-palette'
import type { MinuteRange } from './linked-data'
import './intraday-chart.css'

use([CanvasRenderer, GridComponent, TooltipComponent, AxisPointerComponent, DataZoomSliderComponent, MarkLineComponent, MarkAreaComponent, BrushComponent, BarChart, LineChart])
type Options = ComposeOption<BarSeriesOption | LineSeriesOption | GridComponentOption | TooltipComponentOption | DataZoomComponentOption | AxisPointerComponentOption | BrushComponentOption>
const EMPTY_POINTS: EtfMinutePoint[] = []
const EMPTY_PRICES: EtfChartPrice[] = []
const INSETS = { left: 46, right: 18 }

export function IntradayChart({ data, turnoverBaseline, prices = EMPTY_PRICES, breadth, breadthFailed, breadthControls, boardControls, range, onRangeChange, onMinuteChange }: {
  data?: EtfIntraday; turnoverBaseline?: EtfTurnoverBaseline | null; prices?: EtfChartPrice[]
  breadth?: EtfMarketStats['breadth']; breadthFailed?: boolean; breadthControls?: ReactNode; boardControls?: ReactNode
  range?: MinuteRange; onRangeChange?: (range: MinuteRange) => void; onMinuteChange?: (minute: string) => void
}) {
  const { t, i18n } = useTranslation('etf')
  const host = useRef<HTMLDivElement>(null)
  const chart = useRef<EChartsType | null>(null)
  const [focus, setFocus] = useState<number | null>(null)
  const points = data?.points ?? EMPTY_POINTS
  const sampleCount = data?.symbols.length ?? 0
  const indexed = useMemo(() => new Map(points.map(point => [point.minute, point])), [points])
  const benchmark = useMemo(() => minuteTurnoverFromCumulative(turnoverBaseline?.cumulative_cny), [turnoverBaseline])
  const moves = useMemo(() => prices.flatMap(price => {
    if (price.previousClose != null && price.previousClose > 0) return [{ ...price,
      values: MINUTES.map(minute => price.closes[minute] == null ? null : price.closes[minute] / price.previousClose! - 1), baseMinute: '' }]
    const move = etfIntradayMove(price.closes)
    return move ? [{ ...price, ...move }] : []
  }), [prices])
  const lastTurnover = points.reduce((last, point) => point.turnover_cny != null ? point.minute : last, '')
  const lastBreadth = Object.keys(breadth?.points ?? {}).sort().pop()
  const gaps = MINUTES.filter(minute => breadth?.through && minute <= breadth.through && !breadth.points[minute]).length
  const number = useMemo(() => new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 2 }), [i18n.language])
  const percent = useMemo(() => new Intl.NumberFormat(i18n.language, { style: 'percent', minimumFractionDigits: 2, maximumFractionDigits: 2, signDisplay: 'exceptZero' }), [i18n.language])
  const amount = (value: number) => `${number.format(value / CNY_PER_YI)} ${t('amountUnit')}`
  const preview = breadth?.preview
  const previewCounts = useMemo(() => MINUTES.map(minute => preview && breadth?.through && minute <= breadth.through && minute <= preview.through && !breadth.points[minute]
    ? (preview.minutes[minute] ?? preview.minimum) || null : null), [breadth, preview])
  const describe = (index: number) => {
    const minute = MINUTES[index], point = indexed.get(minute), counts = breadth?.points[minute]
    return [minute, `${t('turnover')}  ${point?.turnover_cny == null ? '—' : amount(point.turnover_cny)}`,
      ...(benchmark[index] == null ? [] : [`${t('minuteAverage', { count: turnoverBaseline?.sessions ?? 5 })}  ${amount(benchmark[index]!)}`]),
      ...moves.map(move => `${move.instrument.name}  ${move.values[index] == null ? '—' : move.baseMinute
        ? t('priceMoveFrom', { time: move.baseMinute, change: percent.format(move.values[index]!) }) : percent.format(move.values[index]!)}`),
      ...(counts ? [t('breadthCounts', counts), ...((counts.source === 'backfill') ? [t('breadthBackfilledMinute')] : [])]
        : breadth?.through && minute <= breadth.through ? [t('breadthMissing')] : []),
      t('pointCoverage', { loaded: point?.etf_count ?? 0, total: sampleCount }),
    ].join('\n')
  }
  const buildOptions = (node: HTMLDivElement): Options => {
    const style = getComputedStyle(node)
    const dark = document.documentElement.classList.contains('dark')
    const color = (token: string) => `hsl(${style.getPropertyValue(token).trim()})`
    const plot = (name: string) => style.getPropertyValue(`--etf-${name}`).trim()
    const border = color('--border'), muted = color('--secondary-foreground')
    const height = node.clientHeight || 640
    const area: LineSeriesOption['markArea'] = range ? { silent: true, itemStyle: { color: dark ? 'rgba(118,169,255,.12)' : 'rgba(57,121,237,.08)' },
      data: [[{ xAxis: range[0] }, { xAxis: range[1] }]] } : undefined
    const hasPrices = moves.length > 0
    const base = data?.previous_close
    const indexReturns = MINUTES.map(minute => {
      const value = indexed.get(minute)?.index_close
      return value != null && base != null && base > 0 ? value / base - 1 : null
    })
    return {
      animation: false, textStyle: { fontFamily: style.fontFamily },
      grid: [
        { ...INSETS, top: 34, height: height * .39 - 40 },
        { ...INSETS, top: height * .44, height: height * .20 - 18 },
        { ...INSETS, top: height * .72, bottom: 54 },
      ],
      axisPointer: { link: [{ xAxisIndex: [0, 1, 2] }] },
      tooltip: { trigger: 'axis', confine: true, renderMode: 'richText', backgroundColor: color('--card'), borderColor: border,
        textStyle: { color: color('--foreground'), fontSize: 11 },
        axisPointer: { type: 'line', lineStyle: { color: muted, type: 'dashed' } },
        formatter: params => { const first = Array.isArray(params) ? params[0] : params; return first ? describe(first.dataIndex) : '' } },
      brush: { xAxisIndex: [0, 1, 2], brushLink: 'all', brushMode: 'single', brushType: 'lineX', transformable: false,
        throttleType: 'debounce', throttleDelay: 180, brushStyle: { color: 'rgba(118,169,255,.12)', borderWidth: 0 } },
      xAxis: [0, 1, 2].map(gridIndex => ({ gridIndex, type: 'category' as const, data: MINUTES, boundaryGap: true,
        axisTick: { show: false }, axisLine: { onZero: false, lineStyle: { color: border } },
        axisLabel: { show: gridIndex === 2, color: muted, fontSize: 10, hideOverlap: true, showMinLabel: true, showMaxLabel: true } })),
      yAxis: [
        { type: 'value', min: 0, splitNumber: 3, axisLabel: { color: muted, fontSize: 10 }, splitLine: { lineStyle: { color: border } } },
        { type: 'value', gridIndex: 1, scale: true, splitNumber: 3,
          min: ({ min, max }) => Math.min(0, min) - Math.max(.001, (max - min) * .08),
          max: ({ min, max }) => Math.max(0, max) + Math.max(.001, (max - min) * .08),
          axisLabel: { color: muted, fontSize: 10, formatter: value => `${(Number(value) * 100).toFixed(1)}%` }, splitLine: { lineStyle: { color: border } } },
        { type: 'value', gridIndex: 2, min: 0, splitNumber: 3, axisLabel: { color: muted, fontSize: 10 }, splitLine: { lineStyle: { color: border } } },
        { type: 'value', gridIndex: 2, show: false, min: 0, max: 1 },
      ],
      dataZoom: [{ id: 'minute-window', type: 'slider', xAxisIndex: [0, 1, 2], ...INSETS, height: 19, bottom: 4,
        minValueSpan: 8, showDetail: false, borderColor: border, backgroundColor: color('--muted'), brushSelect: false,
        fillerColor: 'rgba(118,169,255,.15)', handleStyle: { color: color('--card'), borderColor: plot('turnover-bar') } }],
      series: [
        { id: 'funds', name: t('turnover'), type: 'bar', stack: 'turnover', barMaxWidth: 9, itemStyle: { color: plot('turnover-bar') }, markArea: area,
          data: MINUTES.map((minute, index) => { const point = indexed.get(minute); if (point?.turnover_cny == null) return null
            return (point.etf_count === sampleCount && benchmark[index] != null ? Math.min(point.turnover_cny, benchmark[index]!) : point.turnover_cny) / CNY_PER_YI }) },
        { id: 'turnover-excess', name: t('excessMinute'), type: 'bar', stack: 'turnover', barMaxWidth: 9, itemStyle: { color: plot('excess-bar') },
          data: MINUTES.map((minute, index) => { const point = indexed.get(minute), usual = benchmark[index]
            return point?.turnover_cny != null && point.etf_count === sampleCount && usual != null ? Math.max(0, point.turnover_cny - usual) / CNY_PER_YI : null }) },
        { id: 'turnover-usual', name: t('minuteAverage', { count: turnoverBaseline?.sessions ?? 5 }), type: 'line', showSymbol: false,
          lineStyle: { color: plot('usual-line'), width: 1.5, type: 'dashed' },
          data: MINUTES.map((minute, index) => minute <= lastTurnover && benchmark[index] != null ? benchmark[index]! / CNY_PER_YI : null) },
        ...(hasPrices ? moves.map((move): LineSeriesOption => ({ id: `overlay-${priceInstrumentKey(move.instrument)}`, name: move.instrument.name,
          type: 'line', xAxisIndex: 1, yAxisIndex: 1, showSymbol: false, connectNulls: false,
          lineStyle: { color: etfPriceColor(move.colorIndex, dark), width: 1.8 }, itemStyle: { color: etfPriceColor(move.colorIndex, dark) }, data: move.values,
          markArea: area, markLine: { silent: true, symbol: 'none', lineStyle: { color: muted, type: 'dashed', opacity: .5 }, label: { show: false }, data: [{ yAxis: 0 }] } }))
          : [{ id: 'index', name: t('index'), type: 'line' as const, xAxisIndex: 1, yAxisIndex: 1, showSymbol: false,
            lineStyle: { color: plot('index-line'), width: 1.8 }, data: indexReturns, markArea: area }]),
        { id: 'breadth-up', name: t('breadthUp'), type: 'line', xAxisIndex: 2, yAxisIndex: 2, showSymbol: false, connectNulls: false,
          lineStyle: { color: color('--market-red'), width: 1.6 }, itemStyle: { color: color('--market-red') },
          data: MINUTES.map(minute => breadth?.points[minute]?.up ?? null), markArea: area },
        { id: 'breadth-down', name: t('breadthDown'), type: 'line', xAxisIndex: 2, yAxisIndex: 2, showSymbol: false, connectNulls: false,
          lineStyle: { color: color('--market-green'), width: 1.6 }, itemStyle: { color: color('--market-green') }, data: MINUTES.map(minute => breadth?.points[minute]?.down ?? null) },
        { id: 'breadth-preview', name: t('breadthPreview'), type: 'bar', xAxisIndex: 2, yAxisIndex: 3,
          itemStyle: { color: color('--primary'), opacity: .3 }, data: previewCounts.map(value => preview && value != null ? Math.min(1, value / preview.total) : null) },
        { id: 'breadth-tooltip', type: 'line', xAxisIndex: 2, yAxisIndex: 2, silent: true, showSymbol: false,
          lineStyle: { opacity: 0 }, emphasis: { disabled: true }, data: MINUTES.map(() => 0) },
      ],
    }
  }
  const settings = useRef(buildOptions); settings.current = buildOptions
  const callbacks = useRef({ onRangeChange, onMinuteChange }); callbacks.current = { onRangeChange, onMinuteChange }
  useLayoutEffect(() => {
    const node = host.current
    if (!node) return
    const instance = init(node); chart.current = instance
    const repaint = () => instance.setOption(settings.current(node), { replaceMerge: ['series'] })
    repaint()
    instance.on('updateAxisPointer', ((event: { axesInfo?: { value?: string | number }[] }) => {
      const raw = event.axesInfo?.[0]?.value
      const minute = typeof raw === 'number' ? MINUTES[raw] : raw
      if (minute && MINUTES.includes(minute)) callbacks.current.onMinuteChange?.(minute)
    }) as never)
    instance.on('brushEnd', ((event: { areas?: { coordRange?: number[] }[] }) => {
      const values = event.areas?.[0]?.coordRange
      if (!values || values.length !== 2) return
      const start = MINUTES[Math.max(0, Math.min(MINUTES.length - 1, Math.round(Math.min(...values))))]
      const end = MINUTES[Math.max(0, Math.min(MINUTES.length - 1, Math.round(Math.max(...values))))]
      if (start && end) callbacks.current.onRangeChange?.([start, end])
    }) as never)
    if (callbacks.current.onRangeChange) instance.dispatchAction({ type: 'takeGlobalCursor', key: 'brush', brushOption: { brushType: 'lineX', brushMode: 'single' } })
    const observer = new ResizeObserver(() => { instance.resize(); repaint() }); observer.observe(node)
    const theme = new MutationObserver(repaint); theme.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'data-market-color-scheme'] })
    return () => { observer.disconnect(); theme.disconnect(); instance.dispose(); chart.current = null }
  }, [])
  useLayoutEffect(() => { if (chart.current && host.current) chart.current.setOption(settings.current(host.current), { replaceMerge: ['series'] }) }, [data, turnoverBaseline, moves, breadth, range, i18n.language, t])
  const lastMinute = [lastTurnover, breadth?.through ?? ''].sort()[1] ?? ''
  return <div className="relative">
    <div className="pointer-events-none absolute inset-x-1 top-0 z-10 flex items-center justify-between gap-2 text-[11px]"><span className="font-semibold">{t('etfMinuteTitle')}</span><div className="flex flex-wrap justify-end gap-x-3 gap-y-1 text-[10px] text-secondary-foreground"><span className="inline-flex items-center gap-1"><i className="h-2 w-2 rounded-sm bg-[var(--etf-turnover-bar)]" />{t('turnover')}</span><span className="inline-flex items-center gap-1"><i className="h-2 w-2 rounded-sm bg-[var(--etf-excess-bar)]" />{t('excessMinute')}</span><span className="inline-flex items-center gap-1"><i className="w-3 border-t border-dashed border-[var(--etf-usual-line)]" />{t('minuteAverage', { count: turnoverBaseline?.sessions ?? 5 })}</span></div></div>
    <div className="pointer-events-none absolute inset-x-1 top-[39%] z-10 flex items-center justify-between gap-2 border-t border-border pt-2 text-[11px]"><span className="shrink-0 font-semibold">{t('indexFeedback')}</span><div className="flex flex-wrap justify-end gap-x-3 gap-y-1 text-secondary-foreground">{moves.map(move => <span key={priceInstrumentKey(move.instrument)} className="inline-flex items-center gap-1"><i className="h-0.5 w-3" style={{ backgroundColor: etfPriceColor(move.colorIndex, document.documentElement.classList.contains('dark')) }} />{move.instrument.name}</span>)}</div></div>
    <div className="absolute inset-x-1 top-[66%] z-10 flex flex-wrap items-center justify-between gap-1 border-t border-border pt-2 text-[11px]">
      <div className="flex min-w-0 items-center gap-2"><span className="shrink-0 font-semibold">{t('breadth')}</span>{boardControls}</div>
      <div className="flex min-w-0 items-center gap-1 text-secondary-foreground">{!lastBreadth && <span>{t(breadthFailed ? 'flowUnavailable' : 'breadthMissing')}</span>}{gaps > 0 && <span className="hidden sm:inline">{t('breadthGaps', { count: gaps })}</span>}{breadthControls}</div>
    </div>
    <div ref={host} role="img" tabIndex={0} aria-label={`${t('chartLabel')} · ${t('breadth')}`} className="h-[640px] w-full rounded-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring sm:h-[680px]"
      onKeyDown={event => {
        if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return
        event.preventDefault(); const last = MINUTES.indexOf(lastMinute); if (last < 0) return
        const next = Math.min(last, Math.max(0, (focus ?? last) + (event.key === 'ArrowLeft' ? -1 : 1)))
        setFocus(next); callbacks.current.onMinuteChange?.(MINUTES[next]); chart.current?.dispatchAction({ type: 'showTip', seriesIndex: 0, dataIndex: next })
      }} onBlur={() => { setFocus(null); chart.current?.dispatchAction({ type: 'hideTip' }) }} />
    <span className="sr-only" aria-live="polite">{focus == null ? '' : describe(focus)}</span>
  </div>
}
