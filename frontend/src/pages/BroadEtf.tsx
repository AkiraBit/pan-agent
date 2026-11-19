import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { Activity, ArrowDownRight, ArrowUpRight, BarChart3, CalendarDays, ChevronLeft, ChevronRight, Minus, PanelLeftClose, PanelLeftOpen, RefreshCw } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { enUS, zhCN } from 'react-day-picker/locale'
import { etfApi, type EtfBreadthBackfillStart, type EtfIntraday, type EtfMarketStats, type EtfTurnoverBaseline } from '@panwatch/api/etf'
import { Button } from '@panwatch/base-ui/components/ui/button'
import { Calendar } from '@panwatch/base-ui/components/ui/calendar'
import { Popover, PopoverContent, PopoverTrigger } from '@panwatch/base-ui/components/ui/popover'
import { IntradayChart } from '@/components/etf/IntradayChart'
import { LinkedEtfPanel } from '@/components/etf/LinkedEtfPanel'
import { EtfPricePicker, EtfPriceStrip, useEtfPriceLines } from '@/components/etf/EtfPriceControls'
import { priceInstrumentKey } from '@/components/etf/price-palette'
import { CNY_PER_YI, ETF_SESSION_MINUTES, VOLUME_THRESHOLD } from '@/components/etf/session'
import {
  DEFAULT_REFRESH_DELAY, hasEtfMinute, marketPhase, MAX_REFRESH_DELAY, nextEtfRefresh,
  shanghaiDate, SHANGHAI_TIMEZONE, useMarketTime, type EtfRefreshSlot,
} from '@/components/etf/market-clock'
import { useLocalStorage } from '@/lib/utils'
import { marketSignTextClass } from '@/lib/market-colors'

const DEFAULT_WIDTH = 216
const MIN_WIDTH = 164
const MAX_WIDTH = 292
const BREADTH_POLL_MS = 4000
const BREADTH_SAMPLE_DELAY = 18_000
const clampWidth = (width: number) => Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, width))
const datePattern = /^\d{4}-\d{2}-\d{2}$/
const firstDate = '2009-01-01'
const phaseTone = {
  marketPreopen: 'bg-amber-500/10 text-amber-700 dark:text-amber-300',
  marketOpen: 'bg-primary/10 text-primary',
  marketClosed: 'bg-muted text-secondary-foreground',
  marketHoliday: 'bg-muted text-secondary-foreground',
}

function quotesChanged(previous: EtfIntraday | undefined, next: EtfIntraday) {
  return !previous || previous.date !== next.date || previous.previous_close !== next.previous_close
    || previous.points.length !== next.points.length || next.points.some((point, i) => {
      const prior = previous.points[i]
      return point.minute !== prior.minute || point.turnover_cny !== prior.turnover_cny
        || point.index_close !== prior.index_close || point.etf_count !== prior.etf_count
    })
}

function sameBreadth(previous: EtfMarketStats['breadth'], next: EtfMarketStats['breadth']) {
  if (previous.through !== next.through) return false
  const a = previous.preview
  const b = next.preview
  if (a !== b && (!a || !b || a.through !== b.through || a.total !== b.total || a.minimum !== b.minimum
    || Object.keys(a.minutes).length !== Object.keys(b.minutes).length
    || Object.entries(b.minutes).some(([minute, count]) => a.minutes[minute] !== count))) return false
  const minutes = Object.keys(next.points)
  return minutes.length === Object.keys(previous.points).length && minutes.every(minute => {
    const before = previous.points[minute]
    const after = next.points[minute]
    return !!before && before.up === after.up && before.down === after.down && before.flat === after.flat && before.source === after.source
  })
}

function calendarDate(value: string) {
  const [year, month, day] = value.split('-').map(Number)
  return new Date(year, month - 1, day, 12)
}

function dateKey(value: Date) {
  const pad = (number: number) => String(number).padStart(2, '0')
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`
}

function EtfSidebar({ collapsed, setCollapsed, width, setWidth, date }: {
  collapsed: boolean; setCollapsed: (value: boolean) => void; width: number; setWidth: (value: number) => void; date: string
}) {
  const { t } = useTranslation('etf')
  const start = useRef<{ x: number; width: number } | null>(null)
  const toggleLabel = t(collapsed ? 'expand' : 'collapse')
  const Toggle = collapsed ? PanelLeftOpen : PanelLeftClose
  return <aside className="relative self-start rounded-xl border border-border bg-card md:sticky md:top-20">
    <div className={`flex min-h-12 items-center gap-2 px-2 ${collapsed ? 'justify-between md:justify-center' : 'justify-between'}`}>
      <span className={`pl-1.5 text-xs font-semibold text-secondary-foreground ${collapsed ? 'md:sr-only' : ''}`}>{t('title')}</span>
      <Button type="button" variant="ghost" size="icon" title={toggleLabel} aria-label={toggleLabel} aria-expanded={!collapsed} aria-controls="etf-section-nav"
        className="size-8 shrink-0 text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring" onClick={() => setCollapsed(!collapsed)}>
        <Toggle aria-hidden className="size-4" />
      </Button>
    </div>
    <nav id="etf-section-nav" aria-label={t('nav')} className={`px-2 pb-2 ${collapsed ? 'hidden md:block' : ''}`}>
      <Link to={date ? `/etf?date=${date}` : '/etf'} aria-current="page" aria-label={t('intraday')} title={collapsed ? t('intraday') : undefined}
        className={`flex min-h-10 items-center gap-2.5 rounded-lg bg-primary/10 text-sm font-semibold text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring ${collapsed ? 'justify-center' : 'px-2.5'}`}>
        <Activity aria-hidden className="size-[17px] shrink-0 text-primary" />
        <span className={collapsed ? 'sr-only' : ''}>{t('intraday')}</span>
      </Link>
    </nav>
    {!collapsed && <div
      role="separator" tabIndex={0} aria-label={t('resize')} aria-orientation="vertical" aria-valuemin={MIN_WIDTH} aria-valuemax={MAX_WIDTH} aria-valuenow={width}
      title={t('resize')} className="absolute -right-[7px] top-1 bottom-1 hidden w-3 touch-none select-none items-center justify-center rounded-full outline-ring hover:bg-primary/10 focus-visible:bg-primary/10 focus-visible:outline md:flex"
      style={{ cursor: 'col-resize' }}
      onDoubleClick={() => setWidth(DEFAULT_WIDTH)}
      onPointerDown={event => {
        if (event.button !== 0) return
        event.currentTarget.setPointerCapture(event.pointerId)
        start.current = { x: event.clientX, width }
      }}
      onPointerMove={event => {
        if (start.current) setWidth(clampWidth(start.current.width + event.clientX - start.current.x))
      }}
      onLostPointerCapture={() => { start.current = null }}
      onKeyDown={event => {
        const next = event.key === 'ArrowLeft' ? width - 16 : event.key === 'ArrowRight' ? width + 16
          : event.key === 'Home' ? MIN_WIDTH : event.key === 'End' ? MAX_WIDTH : null
        if (next == null) return
        event.preventDefault()
        setWidth(clampWidth(next))
      }}
    ><span aria-hidden className="h-7 w-0.5 rounded-full bg-border" /></div>}
  </aside>
}

function DateControls({ date, current, calendar, busy, select, refresh }: {
  date: string; current?: EtfIntraday; calendar?: EtfIntraday; busy: boolean; select: (value: string) => void; refresh: () => void
}) {
  const { t, i18n } = useTranslation('etf')
  const [open, setOpen] = useState(false)
  const selected = datePattern.test(date) ? calendarDate(date) : undefined
  const refreshable = !current || current.status === 'live' || current.issues.length > 0
  const arrowClass = 'size-9 shrink-0 focus-visible:ring-2 focus-visible:ring-ring'
  return <div className="flex max-w-full flex-wrap items-center gap-2">
    <div className="flex items-center rounded-lg border border-border bg-card">
      <Button variant="ghost" size="icon" className={arrowClass} title={t('previous')} aria-label={t('previous')}
        disabled={!current?.previous} onClick={() => current?.previous && select(current.previous)}><ChevronLeft aria-hidden className="size-4" /></Button>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button variant="ghost" size="sm" className="h-9 min-w-32 justify-center rounded-none border-x border-border px-3 tabular-nums focus-visible:ring-2 focus-visible:ring-ring" aria-label={t('date')}>
            <CalendarDays aria-hidden className="size-4 text-muted-foreground" />{date || t('date')}
          </Button>
        </PopoverTrigger>
        <PopoverContent aria-label={t('date')} align="end" collisionPadding={8} className="w-auto max-w-[calc(100vw-1rem)] p-0 !animate-none">
          <Calendar mode="single" selected={selected} defaultMonth={selected} showOutsideDays={false} captionLayout="dropdown"
            startMonth={calendarDate(firstDate)} endMonth={calendar?.today ? calendarDate(calendar.today) : undefined}
            disabled={[{ before: calendarDate(firstDate) }, ...(calendar?.today ? [{ after: calendarDate(calendar.today) }] : []), { dayOfWeek: [0, 6] }]}
            locale={i18n.language === 'zh-CN' ? zhCN : enUS}
            onSelect={value => { if (value) { select(dateKey(value)); setOpen(false) } }} />
          <div className="border-t border-border px-2 py-1">
            <Button variant="ghost" size="sm" className="w-full text-primary" onClick={() => { select(''); setOpen(false) }}>{t('latest')}</Button>
          </div>
        </PopoverContent>
      </Popover>
      <Button variant="ghost" size="icon" className={arrowClass} title={t('next')} aria-label={t('next')}
        disabled={!current?.next} onClick={() => current?.next && select(current.next)}><ChevronRight aria-hidden className="size-4" /></Button>
    </div>
    {calendar?.latest && date !== calendar.latest && <Button variant="outline" size="sm" className="h-9 focus-visible:ring-2 focus-visible:ring-ring" onClick={() => select('')}>{t('latest')}</Button>}
    {refreshable && <Button variant="outline" size="icon" className={arrowClass} title={t('refresh')} aria-label={t('refresh')} disabled={busy} onClick={refresh}>
      <RefreshCw aria-hidden className={`size-4 ${busy ? 'motion-safe:animate-spin' : ''}`} />
    </Button>}
  </div>
}

export default function BroadEtf() {
  const { t, i18n } = useTranslation('etf')
  const [params, setParams] = useSearchParams()
  const date = params.get('date') ?? ''
  const [collapsed, setCollapsed] = useLocalStorage('panwatch_etf_sidebar_collapsed', false)
  const [savedWidth, setWidth] = useLocalStorage('panwatch_etf_sidebar_width', DEFAULT_WIDTH)
  const width = Number.isFinite(savedWidth) ? clampWidth(savedWidth) : DEFAULT_WIDTH
  const [state, setState] = useState<{
    date: string; data?: EtfIntraday; busy: boolean; failed?: boolean; offset?: number; refreshedAt?: string
  }>({ date, busy: true })
  const [attempt, setAttempt] = useState(0)
  const [marketStats, setMarketStats] = useState<{ date: string; result: EtfMarketStats | null }>()
  const [statsAttempt, reloadStats] = useState(0)
  const [backfillAction, setBackfillAction] = useState<{ date: string; status: EtfBreadthBackfillStart | 'sending' | 'failed' }>()
  const pendingBackfillDate = useRef<string>()
  const lastBackfillRead = useRef<{ date: string; at: number }>()
  const lastBreadthSlot = useRef<EtfRefreshSlot>()
  const [baselineAttempt, retryBaseline] = useState(0)
  const [lag, setLag] = useState<{ day: string; delay: number }>()
  const [reference, setReference] = useState<{ date: string; attempt: number; value: EtfTurnoverBaseline | null }>()
  const pendingRefresh = useRef<{ date: string; slot?: EtfRefreshSlot } | null>(null)
  const lastAutoRefresh = useRef<EtfRefreshSlot>()
  const lastMarketResync = useRef<string>()
  const requestRefresh = useCallback((slot?: EtfRefreshSlot) => {
    if (slot) lastAutoRefresh.current = slot
    pendingRefresh.current = { date, slot }
    setAttempt(id => id + 1)
  }, [date])
  const refresh = () => {
    requestRefresh()
    reloadStats(id => id + 1)
  }

  useEffect(() => {
    const controller = new AbortController()
    const request = pendingRefresh.current?.date === date ? pendingRefresh.current : null
    pendingRefresh.current = null
    setState(previous => ({ ...previous, date, busy: true, failed: false }))
    etfApi.intraday(date, !!request, controller.signal)
      .then(data => {
        if (controller.signal.aborted) return
        const receivedAt = Date.now()
        const serverAt = data.market?.at
        const offset = serverAt ? Date.parse(serverAt) - receivedAt : 0
        const slot = request?.slot
        if (request && !slot) retryBaseline(id => id + 1)
        if (slot && data.date === slot.day && !data.issues.length && !hasEtfMinute(data, slot.day, slot.minute)) {
          setLag(previous => ({
            day: slot.day,
            delay: Math.min(MAX_REFRESH_DELAY, (previous?.day === slot.day ? previous.delay : DEFAULT_REFRESH_DELAY) + 6_000),
          }))
        }
        setState(previous => {
          const current = previous.data?.date === data.date ? previous.refreshedAt : undefined
          const updated = !!data.points.length && (!current || quotesChanged(previous.data, data))
          return { date, data, busy: false, offset, refreshedAt: updated ? (serverAt ?? new Date(receivedAt).toISOString()) : current }
        })
      })
      .catch(() => { if (!controller.signal.aborted) setState(previous => ({ ...previous, busy: false, failed: true })) })
    return () => controller.abort()
  }, [date, attempt])

  const calendar = state.data
  const data = state.date === date && state.data?.date === (date || state.data?.latest) ? state.data : undefined
  const market = calendar?.market
  const offset = state.offset ?? 0
  const breadthClock = useRef({ market, offset })
  breadthClock.current = { market, offset }
  const statsDate = data?.date ?? (state.date === date && state.failed ? date : null)
  useEffect(() => {
    if (statsDate === null) return
    const controller = new AbortController()
    let timer: number
    let reading = false
    let polling = lastBackfillRead.current?.date === statsDate || pendingBackfillDate.current === statsDate
    const nextSlot = () => {
      const { market, offset } = breadthClock.current
      const now = Date.now() + offset
      return { now, slot: market && nextEtfRefresh(now, market, statsDate, BREADTH_SAMPLE_DELAY, lastBreadthSlot.current, undefined) }
    }
    const schedule = () => {
      window.clearTimeout(timer)
      if (reading || document.visibilityState === 'hidden') return
      if (polling) {
        const elapsed = lastBackfillRead.current?.date === statsDate ? Date.now() - lastBackfillRead.current.at : BREADTH_POLL_MS
        timer = window.setTimeout(read, Math.max(0, BREADTH_POLL_MS - elapsed))
        return
      }
      const { now, slot } = nextSlot()
      if (slot) timer = window.setTimeout(read, Math.max(0, slot.at - now))
    }
    const read = () => {
      if (reading || controller.signal.aborted) return
      const { now, slot } = nextSlot()
      if (slot && slot.at <= now) lastBreadthSlot.current = slot
      reading = true
      etfApi.marketStats(statsDate, controller.signal).then(result => {
        if (controller.signal.aborted) return
        reading = false
        setMarketStats(previous => {
          const prior = previous?.date === statsDate ? previous.result : null
          // Progress can tick without any newly complete minutes. Keep the
          // chart's data reference stable so those polls don't repaint it.
          if (prior?.date === result.date && sameBreadth(prior.breadth, result.breadth)) {
            return { date: statsDate, result: { ...result, breadth: prior.breadth } }
          }
          return { date: statsDate, result }
        })
        setBackfillAction(action => action?.date === result.date && action.status === 'running' ? undefined : action)
        polling = result.backfill?.status === 'running'
        if (polling) {
          lastBackfillRead.current = { date: statsDate, at: Date.now() }
        } else {
          if (lastBackfillRead.current?.date === statsDate) lastBackfillRead.current = undefined
          if (pendingBackfillDate.current === result.date) pendingBackfillDate.current = undefined
        }
        schedule()
      }, () => {
        if (controller.signal.aborted) return
        reading = false
        if (polling || pendingBackfillDate.current === statsDate) {
          polling = true
          lastBackfillRead.current = { date: statsDate, at: Date.now() }
        }
        else setMarketStats({ date: statsDate, result: null })
        schedule()
      })
    }
    const last = lastBackfillRead.current
    const delay = last?.date === statsDate ? BREADTH_POLL_MS - (Date.now() - last.at) : 0
    if (delay > 0) timer = window.setTimeout(read, delay)
    else read()
    document.addEventListener('visibilitychange', schedule)
    return () => {
      controller.abort()
      window.clearTimeout(timer)
      document.removeEventListener('visibilitychange', schedule)
    }
  }, [statsDate, statsAttempt])
  const stats = statsDate !== null && marketStats?.date === statsDate ? marketStats.result : undefined
  const fillDate = stats?.date
  const action = backfillAction?.date === fillDate ? backfillAction?.status : undefined
  const fillRunning = action === 'sending' || action === 'running' || stats?.backfill?.status === 'running'
  const startBackfill = () => {
    if (!fillDate || fillRunning) return
    setBackfillAction({ date: fillDate, status: 'sending' })
    etfApi.backfillBreadth(fillDate).then(({ status }) => {
      if (status === 'running') pendingBackfillDate.current = fillDate
      setBackfillAction({ date: fillDate, status })
      if (status === 'running' || status === 'nothing_to_fill') reloadStats(id => id + 1)
    }, () => setBackfillAction({ date: fillDate, status: 'failed' }))
  }
  const priceLines = useEtfPriceLines(data?.date, data?.status === 'live', attempt)
  const prices = useMemo(() => priceLines.rows.flatMap(({ instrument, colorIndex, quote }) =>
    quote && Object.keys(quote.closes).length ? [{ instrument, colorIndex, closes: quote.closes }] : []), [priceLines.rows])
  const busy = state.busy || state.date !== date
  const marketNow = useMarketTime(offset)
  const marketZone = market?.timezone ?? SHANGHAI_TIMEZONE
  const marketDate = shanghaiDate(marketNow, marketZone)
  const phase = marketPhase(marketNow, marketDate, market)
  const refreshedAt = data ? state.refreshedAt : undefined
  const refreshTime = refreshedAt ? new Intl.DateTimeFormat(i18n.language, {
    timeZone: marketZone, hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).format(Date.parse(refreshedAt)) : '—'

  useEffect(() => {
    if (!market || busy) return
    let timer: number
    const schedule = () => {
      window.clearTimeout(timer)
      if (document.visibilityState === 'hidden') return
      const now = Date.now() + offset
      const day = shanghaiDate(now, market.timezone)
      // If a sleeping tab missed the next session entirely, resync the calendar once.
      if (!date && market.next_trading_day && day > market.next_trading_day && lastMarketResync.current !== day) {
        lastMarketResync.current = day
        requestRefresh()
        return
      }
      const delay = lag?.day === day ? lag.delay : DEFAULT_REFRESH_DELAY
      const slot = nextEtfRefresh(now, market, date, delay, lastAutoRefresh.current, data)
      if (!slot) return
      if (slot.at <= now) requestRefresh(slot)
      else timer = window.setTimeout(schedule, Math.min(slot.at - now, 2_147_483_647))
    }
    schedule()
    document.addEventListener('visibilitychange', schedule)
    return () => {
      window.clearTimeout(timer)
      document.removeEventListener('visibilitychange', schedule)
    }
  }, [market, busy, date, data, offset, lag, requestRefresh])
  const selectedDate = date || data?.date || ''
  const select = (value: string) => setParams(value ? { date: value } : {})
  const hasData = !!data?.points.length
  const turnoverPoints = data?.points.filter(point => point.turnover_cny != null) ?? []
  const lastTurnover = turnoverPoints[turnoverPoints.length - 1]
  const total = turnoverPoints.reduce((sum, point) => sum + (point.turnover_cny ?? 0), 0)
  const complete = !!lastTurnover && turnoverPoints.every((point, index) =>
    point.etf_count === data?.symbols.length && point.minute === ETF_SESSION_MINUTES[index])
  const baselineState = data?.turnover_baseline
  const referenceDate = baselineState?.status === 'needs_calculation' ? data?.date : undefined
  useEffect(() => {
    setReference(undefined)
    if (!referenceDate) return
    const controller = new AbortController()
    const apply = (value: EtfTurnoverBaseline | null) => {
      if (!controller.signal.aborted) setReference({ date: referenceDate, attempt: baselineAttempt, value })
    }
    etfApi.turnoverBaseline(referenceDate, controller.signal).then(apply, () => apply(null))
    return () => controller.abort()
  }, [referenceDate, baselineAttempt])

  const referenceCurrent = !!referenceDate && reference?.date === referenceDate && reference.attempt === baselineAttempt
  const baseline = baselineState?.status === 'ready' ? baselineState.value : referenceCurrent ? reference?.value : undefined
  const baselinePending = !!referenceDate && !referenceCurrent
  const mean = complete && lastTurnover ? baseline?.cumulative_cny[lastTurnover.minute] : undefined
  const change = mean != null && mean > 0 ? total / mean - 1 : null
  const format = new Intl.NumberFormat(i18n.language, { minimumFractionDigits: 1, maximumFractionDigits: 1 })
  const tailPoints = turnoverPoints.slice(-20)
  const tailTotal = tailPoints.length === 20 && tailPoints.every(p => p.etf_count === data?.symbols.length)
    ? tailPoints.reduce((sum, p) => sum + (p.turnover_cny ?? 0), 0) : null
  const tailEnd = tailPoints[tailPoints.length - 1]?.minute
  const tailBefore = tailPoints[0] ? ETF_SESSION_MINUTES[ETF_SESSION_MINUTES.indexOf(tailPoints[0].minute) - 1] : undefined
  const tailMean = tailEnd && baseline?.cumulative_cny[tailEnd] != null
    ? baseline.cumulative_cny[tailEnd] - (tailBefore ? baseline.cumulative_cny[tailBefore] ?? NaN : 0) : null
  const flow = stats?.daily_flow
  const flowValue = flow?.net_cny
  const flowFormat = new Intl.NumberFormat(i18n.language, { minimumFractionDigits: 1, maximumFractionDigits: 1, signDisplay: 'exceptZero' })
  const flowTone = flowValue === 0 ? 'text-foreground' : marketSignTextClass(flowValue)
  const breadthThrough = stats?.breadth.through
  const hasBreadthGap = !!breadthThrough && ETF_SESSION_MINUTES.some(minute =>
    minute <= breadthThrough && !stats.breadth.points[minute])
  const backfill = stats?.backfill
  const stockCount = new Intl.NumberFormat(i18n.language)
  const jobCount = {
    processed: stockCount.format(backfill?.processed ?? 0), total: stockCount.format(backfill?.total ?? 0),
  }
  const fillMessage = fillRunning ? (backfill?.status === 'running' && backfill.reason === 'rate_limited' ? t('breadthFillPaused')
    : backfill?.status === 'running' && backfill.total
    ? backfill.added > 0 ? t('breadthFillProgressWithMinutes', { ...jobCount, count: backfill.added }) : t('breadthFillProgress', jobCount)
    : t('breadthFillStarting'))
    : action === 'busy' ? t('breadthFillBusy')
      : action === 'cooldown' || backfill?.reason === 'rate_limited' ? t('breadthFillCooldown')
        : action === 'failed' || action === 'unavailable' || backfill?.status === 'failed' ? t('breadthFillFailed')
          : backfill?.status === 'partial' ? t('breadthFillPartial', { ...jobCount, count: backfill.added })
            : backfill?.status === 'complete' ? t('breadthFillComplete', { count: backfill.added }) : null
  const fillDetail = !fillRunning && backfill?.reason && backfill.reason !== 'missing_stocks' && backfill.reason !== 'missing_minutes'
    ? t(`issues.${backfill.reason}`) : fillMessage
  const fillWindow = backfill?.through && fillDate ? t('breadthFillWindow', { date: fillDate, time: backfill.through }) : null
  const breadthControls = (hasBreadthGap || fillRunning || fillMessage) && <>
    {fillMessage && <span role="status" className="truncate" title={[fillWindow, fillDetail].filter(Boolean).join(' · ')}>
      {fillMessage}{fillRunning && backfill?.through && ` · ${t('through', { time: backfill.through })}`}
    </span>}
    {(hasBreadthGap || fillRunning) && <Button type="button" size="sm" variant="outline"
      className="pointer-events-auto h-6 shrink-0 px-2 text-[11px]" disabled={fillRunning}
      title={t('breadthFillHint')} onClick={startBackfill}>
      {fillRunning && <RefreshCw aria-hidden className="mr-1 size-3 motion-safe:animate-spin" />}
      {t('breadthFill')}
    </Button>}
  </>
  const percent = new Intl.NumberFormat(i18n.language, { style: 'percent', maximumFractionDigits: 1 })
  const volume = change == null || mean == null ? null : total >= mean * (1 + VOLUME_THRESHOLD) ? 'elevated'
    : total <= mean * (1 - VOLUME_THRESHOLD) ? 'subdued' : 'typical'
  const flat = change != null && Math.abs(change) < .0005
  const Trend = flat || change == null ? Minus : change > 0 ? ArrowUpRight : ArrowDownRight
  const trendClass = flat || change == null ? 'bg-muted text-secondary-foreground' : change > 0
    ? 'bg-market-up/10 text-market-up' : 'bg-market-down/10 text-market-down'
  const sampleGroups = data ? [
    { label: 'verifiedBasket', symbols: data.symbols.filter(symbol => data.disclosures[symbol]) },
    { label: 'extendedBasket', symbols: data.symbols.filter(symbol => !data.disclosures[symbol]) },
  ] as const : []
  const noDataMessage = state.failed || data?.issues.length ? 'unavailable'
    : data?.status === 'closed' ? 'closed' : data?.status === 'waiting' ? 'waiting' : 'empty'
  const recovery = data?.issues.some(issue => issue === 'key_required' || issue === 'permission_required' || issue === 'source_disabled')
  const recoveryPath = data?.issues.includes('source_disabled') ? '/datasources' : '/settings#sec-data-providers'
  const previousSession = data?.status === 'live' && data.issues.includes('permission_required') ? data.previous : null

  return <div className="grid grid-cols-1 gap-3 md:grid-cols-[var(--etf-panel-width)_minmax(0,1fr)] md:gap-4 xl:gap-5"
    style={{ '--etf-panel-width': `${collapsed ? 60 : width}px` } as CSSProperties}>
    <EtfSidebar collapsed={collapsed} setCollapsed={setCollapsed} width={width} setWidth={setWidth} date={datePattern.test(date) ? date : ''} />
    <section className="min-w-0 space-y-4" aria-labelledby="etf-view-title">
      <header className="flex flex-wrap items-center justify-between gap-3 py-0.5">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <h1 id="etf-view-title" className="text-2xl font-bold tracking-tight text-foreground sm:text-[28px]">{t('intraday')}</h1>
          <span className="inline-flex items-center gap-2 rounded-lg border border-border bg-card p-1 pl-2.5 text-xs text-secondary-foreground" title={t('marketTimezone')}>
            <time dateTime={marketDate} className="tabular-nums">{marketDate}</time>
            {phase && <span className={`rounded-md px-1.5 py-0.5 font-medium ${phaseTone[phase]}`}>{t(phase)}</span>}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <p className="flex items-center gap-1.5 whitespace-nowrap text-xs text-secondary-foreground" title={t('marketTimezone')}>
            {t('lastRefresh')}
            {refreshedAt ? <time dateTime={refreshedAt} className="font-medium tabular-nums text-foreground">{refreshTime}</time> : <span>—</span>}
          </p>
          <DateControls date={selectedDate} current={data} calendar={calendar} busy={busy} select={select} refresh={refresh} />
        </div>
      </header>

      <article className="overflow-hidden rounded-xl border border-border bg-card shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-4 border-b border-border/70 px-4 py-4 sm:px-6 sm:py-5">
          <div className="min-w-0 space-y-2">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h2 className="text-lg font-semibold tracking-tight text-foreground sm:text-xl">{t('minuteTurnover')}</h2>
              {!!data?.symbols.length && <span className="text-xs text-secondary-foreground sm:text-sm">{t('watchlistTotal', { count: data.symbols.length })}</span>}
            </div>
            {lastTurnover && <p className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-xs text-secondary-foreground" aria-live="polite">
              {volume ? <span className="font-semibold text-foreground">{t(volume)}</span>
                : <span>{t(!complete ? 'partialTurnover' : baselinePending ? 'baselineLoading' : 'baselineUnavailable')}</span>}
              {baseline && volume && <span>{t('baselinePeriod', { count: baseline.sessions })}{lastTurnover.minute !== '15:00'
                && ` · ${t('through', { time: lastTurnover.minute })}`}</span>}
            </p>}
          </div>
          {(lastTurnover || flow) && <div className="flex w-full flex-wrap items-center gap-x-5 gap-y-3 border-t border-border/60 pt-3 sm:w-auto sm:border-t-0 sm:pt-0">
            {lastTurnover && <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
              <div className="space-y-1 text-xs text-secondary-foreground">
                <p>{t(!complete ? 'observedTurnover' : data?.date === data?.today ? 'todayTurnover' : 'total')}</p>
                {change != null ? <span className={`inline-flex items-center gap-1 rounded-full px-2 py-1 font-medium tabular-nums ${trendClass}`}>
                  <Trend aria-hidden className="size-3.5" />
                  {flat ? t('flat') : t(change > 0 ? 'aboveAverage' : 'belowAverage', { change: percent.format(Math.abs(change)) })}
                </span> : <p>{t('through', { time: lastTurnover.minute })}</p>}
              </div>
              <p className="flex items-baseline gap-1.5 text-3xl font-semibold leading-none tracking-tight tabular-nums text-foreground sm:text-4xl">
                {format.format(total / CNY_PER_YI)} <span className="text-xs font-medium tracking-normal text-secondary-foreground">{t('amountUnit')}</span>
              </p>
            </div>}
            {tailTotal != null && <div className="space-y-1 border-l border-border/80 pl-5"><p className="text-xs text-secondary-foreground">{t('last20Minutes')}</p><p className="text-xl font-semibold tabular-nums">{format.format(tailTotal / CNY_PER_YI)} <span className="text-xs font-normal text-secondary-foreground">{t('amountUnit')}</span></p><p className="text-[10px] text-secondary-foreground">{tailMean != null && tailMean > 0 ? t('timesBaseline', { value: (tailTotal / tailMean).toFixed(1) }) : t('baselineUnavailable')}</p></div>}
            {flow && <div className={`space-y-1 ${lastTurnover ? 'border-l border-border/80 pl-5' : ''}`} title={t('methodFlow')} aria-live="polite">
              <p className="text-xs text-secondary-foreground">{t('dailyFlow', { count: flow.total })}</p><p className="text-[10px] text-secondary-foreground">{t('dataAsOf', { date: stats?.date })}</p>
              {flowValue != null ? <p className={`text-xl font-semibold leading-none tracking-tight tabular-nums ${flowTone}`}>
                {flowFormat.format(flowValue / CNY_PER_YI)} <span className="text-xs font-medium tracking-normal text-secondary-foreground">{t('amountUnit')}</span>
              </p> : <p className="text-xs font-medium text-secondary-foreground">
                {flow.status === 'partial' ? t('flowCoverage', flow) : t(flow.status === 'pending' ? 'flowPending' : 'flowUnavailable')}
              </p>}
            </div>}
          </div>}
        </div>
        {hasData && data ? <div className="etf-intraday-chart">
          <EtfPriceStrip selection={priceLines.selection} />
          {priceLines.rows.map(({ instrument, failed, quote }) => {
            const issue = quote?.issue
            const status = failed ? 'priceLoadFailed' : issue === 'unknown_etf' ? 'priceUnknown' : issue === 'unknown_index' ? 'priceUnknownIndex'
              : issue ? `issues.${issue}` as const : !quote ? 'priceLoading'
                : !Object.keys(quote.closes).length ? 'priceEmpty' : !quote.complete && data.status === 'archive' ? 'pricePartial' : null
            return status && <div key={priceInstrumentKey(instrument)} className="flex flex-wrap items-center justify-center gap-1 px-4 pt-1 text-xs text-secondary-foreground">
              <p role="status">{instrument.name} · {t(status)}</p>
              {status !== 'priceLoading' && <Button type="button" size="sm" variant="ghost" className="h-6 px-2 text-xs"
                onClick={() => priceLines.retryPrice(instrument)}>{t('retry')}</Button>}
            </div>
          })}
          <div className="px-1.5 sm:px-4"><LinkedEtfPanel key={data.date} data={data} turnoverBaseline={baseline} prices={prices}
            breadth={stats?.breadth} breadthFailed={stats === null} breadthControls={breadthControls}
            priceControls={<EtfPricePicker selection={priceLines.selection} onChange={priceLines.setVisible} />} /></div>
          {(busy || state.failed || data.issues.length > 0) && <div className="space-y-1 px-4 pb-3 text-xs leading-relaxed text-secondary-foreground sm:px-6" aria-live="polite">
            {busy && <p>{t('refreshing')}</p>}
            {state.failed && <p>{t('unavailable')}</p>}
            {data.issues.map(issue => <p key={issue}>{t(`issues.${issue}`)}</p>)}
            {recovery && <Link to={recoveryPath} className="font-medium text-primary underline-offset-2 hover:underline">{t('configure')}</Link>}
          </div>}
        </div> : <div className="mx-4 my-4 flex min-h-[310px] flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border bg-muted/25 px-6 py-12 text-center sm:mx-6"
          role={busy ? 'status' : state.failed || data?.issues.length ? 'alert' : undefined}>
          {busy ? <RefreshCw aria-hidden className="size-6 text-primary motion-safe:animate-spin" /> : <BarChart3 aria-hidden className="size-7 text-muted-foreground" />}
          <p className="text-sm font-semibold text-foreground">{t(busy ? 'loading' : noDataMessage)}</p>
          {!busy && data?.issues.map(issue => <p className="max-w-md text-xs text-secondary-foreground" key={issue}>{t(`issues.${issue}`)}</p>)}
          {!busy && <div className="flex flex-wrap justify-center gap-2">
            {previousSession && <Button size="sm" onClick={() => select(previousSession)}>{t('viewPrevious')}</Button>}
            {recovery && <Button asChild size="sm" variant="outline"><Link to={recoveryPath}>{t('configure')}</Link></Button>}
            {(state.failed || data?.issues.length || data?.status === 'live') ? <Button size="sm" variant="secondary" onClick={refresh}>{t('retry')}</Button> : null}
          </div>}
        </div>}
        {!hasData && stats?.breadth.through && <div className="etf-intraday-chart px-1.5 sm:px-4">
          <IntradayChart key={stats.date} breadth={stats.breadth} breadthControls={breadthControls} />
        </div>}
        <details className="border-t border-border px-4 py-3 text-xs text-secondary-foreground sm:px-6">
          <summary className="w-fit cursor-pointer rounded-sm font-semibold text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring">{t('methodology')}</summary>
          <div className="mt-3 space-y-2 leading-relaxed">
            <p>{t('methodIntro')}</p>
            <p><strong className="font-semibold text-foreground">{t('methodAverageLabel')}</strong>{' '}{t('methodAverage')}</p>
            <p>{t('methodVolume', { threshold: percent.format(VOLUME_THRESHOLD) })}</p>
            <p>{t('methodBreadth')}</p>
            <p>{t('methodFlow')}</p>
            {priceLines.selection.items.length > 0 && <p>{t('methodPriceMove')}</p>}
            <p>{t('methodSelection')}</p>
            {!!data?.symbols.length && <>
              <p className="font-medium text-foreground">{t('basket', { count: data.symbols.length })}</p>
              {sampleGroups.filter(group => group.symbols.length > 0).map(group => (
                <div key={group.label} className="space-y-1">
                  <p>{t(group.label, { count: group.symbols.length })}</p>
                  <ul className="flex flex-wrap gap-1.5">{group.symbols.map(symbol => {
                    const disclosure = data.disclosures[symbol]
                    const name = data.names?.[symbol]
                    const label = <>{name && <span>{name}</span>}<span className="font-mono tabular-nums text-secondary-foreground">{symbol}</span></>
                    const chip = "inline-flex flex-wrap items-baseline gap-x-2 rounded-md px-2 py-1 text-foreground"
                    return <li key={symbol}>
                      {disclosure ? <a href={disclosure.url} target="_blank" rel="noreferrer"
                        className={`${chip} bg-primary/10 underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring`}
                        title={t('reportLink', { date: disclosure.report_date })}>{label}</a>
                        : <span className={`${chip} bg-muted`}>{label}</span>}
                    </li>
                  })}</ul>
                </div>
              ))}
            </>}
          </div>
        </details>
      </article>
    </section>
  </div>
}
