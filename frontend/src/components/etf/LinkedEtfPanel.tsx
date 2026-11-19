import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { ArrowRight, ChevronDown, ChevronUp, RefreshCw } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { etfApi, type EtfBoard, type EtfComponents, type EtfGroupId, type EtfIntraday, type EtfLinkedAnalysis, type EtfMarketStats, type EtfTurnoverBaseline } from '@panwatch/api/etf'
import { Button } from '@panwatch/base-ui/components/ui/button'
import { marketSignTextClass } from '@/lib/market-colors'
import { IntradayChart } from './IntradayChart'
import { ETF_SESSION_MINUTES as MINUTES, CNY_PER_YI } from './session'
import { baselineAmount, rangeAmounts, selectTurnover, type MinuteRange } from './linked-data'
import type { EtfChartPrice } from './price-palette'

export function LinkedEtfPanel({ data, turnoverBaseline, prices, breadth, breadthFailed, breadthControls, priceControls }: {
  data: EtfIntraday; turnoverBaseline?: EtfTurnoverBaseline | null; prices: EtfChartPrice[]
  breadth?: EtfMarketStats['breadth']; breadthFailed?: boolean; breadthControls?: ReactNode; priceControls?: ReactNode
}) {
  const { t, i18n } = useTranslation('etf')
  const [analysis, setAnalysis] = useState<EtfLinkedAnalysis>()
  const [failed, setFailed] = useState(false)
  const [attempt, retry] = useState(0)
  const [group, setGroup] = useState<EtfGroupId | 'all'>('all')
  const [board, setBoard] = useState<EtfBoard>('all')
  const last = data.points[data.points.length - 1]?.minute ?? '09:30'
  const [range, setRange] = useState<MinuteRange>(() => [MINUTES[Math.max(0, MINUTES.indexOf(last) - 19)], last])
  const [cursor, setCursor] = useState(last)
  const [expanded, setExpanded] = useState(false)
  const [detailGroup, setDetailGroup] = useState<EtfGroupId>('csi300')
  const [components, setComponents] = useState<EtfComponents>()
  const [detailFailed, setDetailFailed] = useState(false)
  const [detailAttempt, retryDetail] = useState(0)
  const [starting, setStarting] = useState(false)
  const through = breadth?.through
  const componentRunning = components?.backfill?.status === 'running'
  useEffect(() => {
    const controller = new AbortController()
    let timer: number
    setFailed(false)
    const read = () => etfApi.analysis(data.date, controller.signal).then(value => { if (!controller.signal.aborted) {
      setAnalysis(value)
      if (value.backfill?.status === 'running') timer = window.setTimeout(read, 4000)
    } }, () => {
      if (!controller.signal.aborted) setFailed(true)
    })
    read()
    return () => { controller.abort(); window.clearTimeout(timer) }
  }, [data.date, last, through, turnoverBaseline, attempt])
  useEffect(() => {
    if (!expanded) return
    const controller = new AbortController()
    let timer: number
    setDetailFailed(false)
    const read = () => etfApi.components(data.date, detailGroup, cursor, controller.signal).then(value => {
      if (controller.signal.aborted) return
      setComponents(value)
      if (value.backfill?.status === 'running') timer = window.setTimeout(read, 4000)
    }, () => { if (!controller.signal.aborted) setDetailFailed(true) })
    // Debounce cursor motion so scrubbing the chart does not flood the API.
    timer = window.setTimeout(read, 220)
    return () => { controller.abort(); window.clearTimeout(timer) }
  }, [data.date, detailGroup, cursor, expanded, detailAttempt])
  const selected = selectTurnover(data, analysis, group, turnoverBaseline)
  const plotPrices = useMemo(() => [
    ...(analysis?.benchmarks ?? []).map((item, index) => ({ instrument: { symbol: item.symbol, kind: 'index' as const, name: t(`groups.${item.group}`) },
      closes: item.closes, previousClose: item.previous_close, colorIndex: [8, 1, 7][index] })),
    ...prices.filter(item => !analysis?.benchmarks.some(b => b.symbol === item.instrument.symbol)),
  ], [analysis, prices, t])
  const activeBreadth = board === 'all' ? breadth : { through: through ?? last, points: Object.fromEntries(Object.entries(analysis?.boards[board] ?? {}).map(([minute, point]) => [minute, { ...point, source: point.source === 'backfill' ? 'backfill' as const : undefined }])) }
  const amount = (value: number | null) => value == null ? '—' : new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 1 }).format(value / CNY_PER_YI)
  const pct = (value: number | null) => value == null ? '—' : new Intl.NumberFormat(i18n.language, { style: 'percent', minimumFractionDigits: 2, maximumFractionDigits: 2, signDisplay: 'exceptZero' }).format(value)
  const actual = rangeAmounts(Object.fromEntries(selected.data.points.map(p => [p.minute, p.turnover_cny])), range)
  const usual = baselineAmount(selected.baseline?.cumulative_cny, range)
  const volumeRatio = actual != null && usual != null && usual > 0 ? actual / usual : null
  const mainIndex = plotPrices.find(item => item.instrument.symbol === (group === 'all' ? '000300.SH' : analysis?.groups.find(item => item.id === group)?.index)) ?? plotPrices[0]
  const first = mainIndex?.closes[range[0]], end = mainIndex?.closes[range[1]]
  const move = first != null && end != null && first > 0 ? end / first - 1 : null
  const counts = activeBreadth?.points
  const breadthChange = counts?.[range[0]] && counts?.[range[1]] ? counts[range[1]].up - counts[range[0]].up : null
  const contributions = (analysis?.groups ?? []).flatMap(item => {
    const value = rangeAmounts(item.points, range), base = baselineAmount(item.baseline, range)
    return value == null || base == null ? [] : [{ id: item.id, value: Math.max(0, value - base) }]
  }).sort((a, b) => b.value - a.value)
  const excessTotal = contributions.reduce((sum, row) => sum + row.value, 0)
  const currentComponents = components?.group === detailGroup && components.minute === cursor && components.date === data.date ? components : undefined
  const showDetail = (id: EtfGroupId) => { setDetailGroup(id); setExpanded(true) }
  const backfill = async () => {
    if (starting || componentRunning) return
    setStarting(true)
    try { const result = await etfApi.backfillComponents(data.date, detailGroup); setDetailFailed(!['running', 'nothing_to_fill'].includes(result.status)); retryDetail(n => n + 1) }
    catch { setDetailFailed(true) }
    finally { setStarting(false) }
  }
  const backfillBoards = async () => {
    try { await etfApi.backfillComponents(data.date, 'all'); retry(n => n + 1) }
    catch { setFailed(true) }
  }
  return <div className="etf-intraday-chart space-y-3 p-3 sm:p-5">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-2"><h2 className="text-base font-semibold">{t('linkedTitle')}</h2>{priceControls}</div>
      <div role="group" aria-label={t('groupSelection')} className="scrollbar flex max-w-full gap-1 overflow-x-auto pb-1">
        {(['all', ...(analysis?.groups.map(item => item.id) ?? [])] as const).map(id => <Button key={id} size="sm" variant={group === id ? 'secondary' : 'ghost'}
          className="h-8 shrink-0 px-2 text-xs" aria-pressed={group === id} onClick={() => setGroup(id)}>{t(`groups.${id}`)}</Button>)}
      </div>
    </div>
    {failed && <div role="status" className="flex items-center gap-2 text-xs text-secondary-foreground">{t('linkedUnavailable')}<Button size="sm" variant="ghost" onClick={() => retry(n => n + 1)}>{t('retry')}</Button></div>}
    <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1fr)_252px]">
      <div className="min-w-0"><IntradayChart data={selected.data} turnoverBaseline={selected.baseline} prices={plotPrices}
        breadth={activeBreadth} breadthFailed={breadthFailed} breadthControls={breadthControls} range={range} onRangeChange={setRange} onMinuteChange={setCursor}
        boardControls={<div className="scrollbar flex max-w-full gap-0.5 overflow-x-auto">
          {(['all', 'main', 'growth', 'star', 'beijing'] as EtfBoard[]).map(id => <Button key={id} size="sm" variant={board === id ? 'secondary' : 'ghost'}
            className="h-6 shrink-0 px-1.5 text-[10px]" aria-pressed={board === id} onClick={() => setBoard(id)}>{t(`boards.${id}`)}</Button>)}
          {board !== 'all' && !Object.keys(analysis?.boards[board] ?? {}).length && <Button size="sm" variant="outline" className="h-6 shrink-0 px-1.5 text-[10px]"
            disabled={analysis?.backfill?.status === 'running'} onClick={backfillBoards}>{t('boardBackfill')}</Button>}
        </div>} /></div>
      <aside className="space-y-5 rounded-lg border border-border p-4" aria-label={t('intervalObservation')}>
        <div className="flex items-center justify-between gap-2"><h3 className="text-sm font-semibold">{t('intervalObservation')}</h3><span className="text-xs tabular-nums text-secondary-foreground">{range.join(' – ')}</span></div>
        <div className="grid grid-cols-2 gap-2 text-xs">
          <label className="space-y-1 text-secondary-foreground">{t('rangeStart')}<input type="time" step="60" value={range[0]} aria-label={t('rangeStart')}
            className="w-full rounded-md border border-input bg-background p-1.5 text-foreground" onChange={e => { const minute = e.target.value.slice(0, 5); if (MINUTES.includes(minute) && minute <= range[1]) setRange([minute, range[1]]) }} /></label>
          <label className="space-y-1 text-secondary-foreground">{t('rangeEnd')}<input type="time" step="60" value={range[1]} aria-label={t('rangeEnd')}
            className="w-full rounded-md border border-input bg-background p-1.5 text-foreground" onChange={e => { const minute = e.target.value.slice(0, 5); if (MINUTES.includes(minute) && minute >= range[0] && minute <= last) setRange([range[0], minute]) }} /></label>
        </div>
        <dl className="space-y-4 text-sm">
          <div className="flex justify-between gap-2"><dt className="text-secondary-foreground">{t('intervalTurnover')}</dt><dd className="font-semibold tabular-nums">{amount(actual)} {t('amountUnit')}</dd></div>
          <div className="flex justify-between gap-2"><dt className="text-secondary-foreground">{t('intervalRatio')}</dt><dd className="font-semibold tabular-nums">{volumeRatio == null ? '—' : t('times', { value: volumeRatio.toFixed(1) })}</dd></div>
          <div className="flex justify-between gap-2"><dt className="text-secondary-foreground">{mainIndex?.instrument.name ?? t('indexFeedback')}</dt><dd className={`font-semibold tabular-nums ${marketSignTextClass(move)}`}>{pct(move)}</dd></div>
          <div className="flex justify-between gap-2"><dt className="text-secondary-foreground">{t('intervalBreadth')}</dt><dd className={`font-semibold tabular-nums ${marketSignTextClass(breadthChange)}`}>{breadthChange == null ? '—' : `${breadthChange > 0 ? '+' : ''}${breadthChange}`}</dd></div>
        </dl>
        <div className="space-y-3 border-t border-border pt-4"><h3 className="text-sm font-semibold">{t('excessSources')}</h3>
          {excessTotal > 0 ? contributions.filter(row => row.value > 0).map(row => <button key={row.id} type="button" onClick={() => showDetail(row.id)}
            className="flex w-full items-center gap-2 rounded-md px-1 py-1 text-xs hover:bg-muted focus-visible:outline focus-visible:outline-ring">
            <span className="w-16 shrink-0 text-left">{t(`groups.${row.id}`)}</span><span className="h-1.5 flex-1 rounded bg-muted"><span className="block h-full rounded bg-primary/70" style={{ width: `${row.value / excessTotal * 100}%` }} /></span>
            <span className="w-8 text-right tabular-nums">{Math.round(row.value / excessTotal * 100)}%</span></button>) : <p className="text-xs text-secondary-foreground">{t('noExcess')}</p>}
          <p className="text-[10px] leading-relaxed text-secondary-foreground">{t('excessSourcesHint')}</p>
        </div>
        <Button variant="ghost" size="sm" className="w-full text-primary" onClick={() => showDetail(group === 'all' ? 'csi300' : group)}>{t('viewComponents')}<ArrowRight className="ml-1 size-3" /></Button>
      </aside>
    </div>
    <section className="rounded-lg border border-border" aria-label={t('componentsTitle')}>
      <Button variant="ghost" className="flex h-auto w-full justify-between px-4 py-3" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
        <span>{t('componentsTitle')} · {t(`groups.${detailGroup}`)}</span>{expanded ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
      </Button>
      {expanded && <div className="space-y-3 border-t border-border p-4">
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-secondary-foreground"><span>{cursor} · {t('componentCoverage', { covered: currentComponents?.covered ?? 0, total: currentComponents?.total ?? 0 })}</span>
          <Button size="sm" variant="outline" disabled={starting || componentRunning} onClick={backfill}>{(starting || componentRunning) && <RefreshCw className="mr-1 size-3 animate-spin" />}{t('componentBackfill')}</Button></div>
        {(detailFailed || currentComponents?.issue) && <p role="status" className="text-xs text-secondary-foreground">{t('componentUnavailable')}</p>}
        {componentRunning && <p role="status" className="text-xs text-secondary-foreground">{t('breadthFillProgress', { processed: currentComponents?.backfill?.processed ?? 0, total: currentComponents?.backfill?.total ?? 0 })}</p>}
        {!currentComponents?.covered ? <p className="py-4 text-sm text-secondary-foreground">{t('componentMissing')}</p> : <>
          <div className="grid gap-5 md:grid-cols-2"><div className="space-y-3">
            <div className="flex justify-between gap-3 text-sm"><span>{t('breadthUp')} <strong>{currentComponents.up} / {currentComponents.covered}</strong></span>
              <span>{t('upRatio')} <strong>{(currentComponents.up / currentComponents.covered * 100).toFixed(1)}%</strong></span>
              <span>{t('medianChange')} <strong className={marketSignTextClass(currentComponents.median)}>{pct(currentComponents.median)}</strong></span></div>
            <div className="flex h-3 overflow-hidden rounded-full" aria-label={t('distribution')}>
              <span className="bg-market-up" style={{ width: `${currentComponents.up / currentComponents.covered * 100}%` }} /><span className="bg-muted-foreground/40" style={{ width: `${currentComponents.flat / currentComponents.covered * 100}%` }} /><span className="bg-market-down" style={{ width: `${currentComponents.down / currentComponents.covered * 100}%` }} />
            </div><p className="text-xs text-secondary-foreground">{t(currentComponents.source === 'backfill' ? 'breadthBackfilledMinute' : 'capturedMinute')}</p>
          </div><div className="grid grid-cols-2 gap-6">{(['leaders', 'laggards'] as const).map(key => <div key={key} className="space-y-2"><h4 className="text-xs font-semibold">{t(key)}</h4>
            {currentComponents[key].map(row => <div key={row.symbol} className="flex justify-between gap-2 text-xs"><span className="truncate" title={row.symbol}>{row.name}</span><span className={`shrink-0 tabular-nums ${marketSignTextClass(row.change)}`}>{pct(row.change)}</span></div>)}
          </div>)}</div></div>
          {currentComponents.weights_date && <p className="text-[10px] text-secondary-foreground">{t('weightsAsOf', { date: currentComponents.weights_date })}</p>}
        </>}
      </div>}
    </section>
  </div>
}
