import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { init, use, type ComposeOption, type EChartsType } from 'echarts/core'
import { BarChart, LineChart, ScatterChart, type BarSeriesOption, type LineSeriesOption, type ScatterSeriesOption } from 'echarts/charts'
import { AxisPointerComponent, DataZoomSliderComponent, GridComponent, type AxisPointerComponentOption, type DataZoomComponentOption, type GridComponentOption } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([CanvasRenderer, GridComponent, AxisPointerComponent, DataZoomSliderComponent, BarChart, LineChart, ScatterChart])

export type EtfChartOption = ComposeOption<BarSeriesOption | LineSeriesOption | ScatterSeriesOption | GridComponentOption | AxisPointerComponentOption | DataZoomComponentOption>
type AxisOption = Exclude<NonNullable<EtfChartOption['xAxis']>, unknown[]>
export const GRID_TOP = 24

function chartColors(host: HTMLElement) {
  const style = getComputedStyle(host)
  const color = (name: string, opacity = 1) => {
    const channels = style.getPropertyValue(name).trim().split(/\s+/)
    return `hsla(${channels.join(',')},${opacity})`
  }
  return {
    text: color('--muted-foreground'),
    grid: color('--border'),
    primary: color('--primary'),
    index: color('--foreground', .65),
    foreground: color('--foreground'),
    volume: color('--muted-foreground', .45),
    up: color('--market-up'),
    down: color('--market-down'),
    flat: color('--market-flat'),
    baseline: '#a86410',
    surge: '#c47d13',
    font: style.fontFamily,
  }
}

export type EtfChartColors = ReturnType<typeof chartColors>

export function signedColor(colors: EtfChartColors, value: number | null) {
  return value == null || value === 0 ? colors.flat : value > 0 ? colors.up : colors.down
}

export function categoryAxis(labels: string[], tick: (value: string, index: number) => string, colors: EtfChartColors) {
  return {
    type: 'category',
    data: labels,
    axisLine: { lineStyle: { color: colors.grid } },
    axisTick: { show: false },
    axisLabel: {
      interval: (index, value) => Boolean(tick(value, index)),
      formatter: tick,
      color: colors.text,
      fontSize: 11,
      hideOverlap: true,
    },
    axisPointer: { show: true, snap: true, label: { show: false }, lineStyle: { color: colors.text, type: 'dashed' } },
  } satisfies AxisOption
}

export function valueAxis(colors: EtfChartColors, formatter: (value: number) => string, position: 'left' | 'right' = 'left') {
  return {
    type: 'value' as const,
    position,
    splitNumber: 3,
    axisLabel: { color: colors.text, fontSize: 11, formatter },
    splitLine: { show: position === 'left', lineStyle: { color: colors.grid } },
  }
}

export function chartBase(colors: EtfChartColors, left: number, right: number): EtfChartOption {
  return {
    animation: false,
    textStyle: { fontFamily: colors.font },
    grid: { left, right, top: GRID_TOP, bottom: 28 },
    axisPointer: { triggerOn: 'none', triggerTooltip: false, triggerEmphasis: false },
  }
}

export function dayTick(count: number, spansYears = false) {
  return (date: string, index: number) => {
    if (index !== 0 && index !== Math.floor(count / 2) && index !== count - 1) return ''
    if (count < 4) return date
    return spansYears ? date.slice(0, 7) : date.slice(5).replace('-', '/')
  }
}

export type ChartWindow = readonly [first: number, last: number]

interface Props {
  className: string
  label: string
  count: number
  gridCount?: number
  option: (colors: EtfChartColors, width: number) => EtfChartOption
  visibleWindow?: ChartWindow
  onWindowChange?: (window: ChartWindow) => void
  showLatest?: boolean
  guideOnLatest?: boolean
  onActivate?: (index: number) => void
  children: (index: number | null) => ReactNode
}

function syncGuide(chart: EChartsType, index: number | null) {
  if (index == null) {
    chart.dispatchAction({ type: 'updateAxisPointer', currTrigger: 'leave' })
    return
  }
  const x = chart.convertToPixel({ xAxisIndex: 0 }, index)
  if (typeof x === 'number' && Number.isFinite(x)) {
    chart.dispatchAction({ type: 'updateAxisPointer', x, y: GRID_TOP + 1 })
  }
}

export function EtfChart({ className, label, count, gridCount = 1, option, visibleWindow, onWindowChange, showLatest, guideOnLatest, onActivate, children }: Props) {
  const hostRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<EChartsType | null>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const [first, last] = visibleWindow ?? [0, count - 1]
  const index = Math.max(first, Math.min(last, selected ?? last))
  const guide = selected != null || guideOnLatest ? index : null
  const current = useRef({ count, gridCount, option, guide, onActivate, onWindowChange })

  useLayoutEffect(() => {
    const previous = current.current
    current.current = { count, gridCount, option, guide, onActivate, onWindowChange }
    const chart = chartRef.current
    const host = hostRef.current
    if (!chart || !host) return
    if (previous.option !== option) chart.setOption(option(chartColors(host), chart.getWidth()), { notMerge: true })
    if (previous.option !== option || previous.guide !== guide) syncGuide(chart, guide)
  }, [count, gridCount, option, guide, onActivate, onWindowChange])

  useLayoutEffect(() => {
    const host = hostRef.current
    if (!host) return
    function setOptions() {
      const chart = chartRef.current
      if (!chart || !host) return
      chart.setOption(current.current.option(chartColors(host), chart.getWidth()), { notMerge: true })
      syncGuide(chart, current.current.guide)
    }

    function resize() {
      if (!host || !host.clientWidth || !host.clientHeight) return
      const existing = chartRef.current
      if (existing) {
        if (existing.getWidth() !== host.clientWidth || existing.getHeight() !== host.clientHeight) {
          existing.resize()
          setOptions()
        }
        return
      }

      const chart = init(host, undefined, { renderer: 'canvas' })
      chartRef.current = chart
      const pointerIndex = ({ offsetX, offsetY }: { offsetX: number; offsetY: number }) => {
        const gridIndex = Array.from({ length: current.current.gridCount }, (_, i) => i)
          .find(i => chart.containPixel({ gridIndex: i }, [offsetX, offsetY]))
        if (gridIndex == null) return null
        const category = chart.convertFromPixel({ xAxisIndex: gridIndex }, offsetX)
        if (typeof category !== 'number' || !Number.isFinite(category)) return null
        return Math.max(0, Math.min(current.current.count - 1, Math.round(category)))
      }
      chart.getZr().on('mousemove', event => setSelected(pointerIndex(event)))
      chart.getZr().on('globalout', () => setSelected(null))
      chart.getZr().on('click', event => {
        const point = pointerIndex(event)
        if (point == null) return
        setSelected(point)
        current.current.onActivate?.(point)
      })
      chart.on('datazoom', () => {
        if (!current.current.onWindowChange) return
        const zoom = (chart.getOption().dataZoom as { startValue?: number; endValue?: number }[] | undefined)?.[0]
        if (zoom?.startValue == null || zoom.endValue == null || !Number.isInteger(zoom.startValue) || !Number.isInteger(zoom.endValue)) return
        const start = Math.max(0, Math.min(current.current.count - 1, zoom.startValue))
        const end = Math.max(start, Math.min(current.current.count - 1, zoom.endValue))
        setSelected(null)
        current.current.onWindowChange([start, end])
      })
      setOptions()
    }

    const size = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(resize)
    size?.observe(host)
    if (!size) window.addEventListener('resize', resize)
    const theme = new MutationObserver(setOptions)
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'data-market-color-scheme'] })
    // A chart inside a closed details element is initialized when it first becomes visible.
    resize()
    return () => {
      size?.disconnect()
      if (!size) window.removeEventListener('resize', resize)
      theme.disconnect()
      chartRef.current?.dispose()
      chartRef.current = null
    }
  }, [])

  return <>
    <div
      className={className}
      ref={hostRef}
      role="img"
      aria-label={label}
      tabIndex={0}
      onKeyDown={event => {
        if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
          event.preventDefault()
          setSelected(Math.max(first, Math.min(last, index + (event.key === 'ArrowLeft' ? -1 : 1))))
        } else if (event.key === 'Enter' && onActivate && (showLatest || selected != null)) {
          event.preventDefault()
          onActivate(index)
        }
      }}
    />
    {children(showLatest || selected != null ? index : null)}
  </>
}
