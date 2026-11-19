import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { etfApi, type EtfIntraday, type EtfMarketStats, type EtfPriceInstrument, type EtfTurnoverBaseline } from '@panwatch/api/etf'
import { marketPhase, nextEtfRefresh } from '@/components/etf/market-clock'
import { etfIntradayMove } from '@/components/etf/session'
import BroadEtf from '@/pages/BroadEtf'

const chartBreadth = vi.hoisted(() => vi.fn())
vi.mock('@panwatch/api/etf', () => ({ etfApi: {
  intraday: vi.fn(), turnoverBaseline: vi.fn(), priceCatalog: vi.fn(), priceLine: vi.fn(), marketStats: vi.fn(),
  backfillBreadth: vi.fn(), analysis: vi.fn().mockResolvedValue({ groups: [], benchmarks: [], boards: {} }), components: vi.fn(), backfillComponents: vi.fn(),
} }))
vi.mock('@/components/etf/IntradayChart', () => ({
  IntradayChart: ({ data, prices = [], breadth, breadthControls }: {
    data?: EtfIntraday; prices?: { instrument: EtfPriceInstrument }[]; breadth?: EtfMarketStats['breadth']; breadthControls?: React.ReactNode
  }) => {
    chartBreadth(breadth)
    return <>
      <div role="img" aria-label={data?.date ?? 'breadth'} data-breadth={breadth && JSON.stringify(breadth.points)}
        data-price={prices.length ? prices.map(price => price.instrument.symbol).join(',') : undefined} />
      {breadthControls}
    </>
  },
}))

const load = vi.mocked(etfApi.intraday)
const reference = vi.mocked(etfApi.turnoverBaseline)
const stats = vi.mocked(etfApi.marketStats)
const startBackfill = vi.mocked(etfApi.backfillBreadth)
const latest = '2026-11-17'
const previous = '2026-11-16'

function session(date = latest): EtfIntraday {
  return {
    date, latest, today: latest, source: 'tushare', broad_count: 293, disclosures: {}, previous: date === latest ? previous : '2026-11-13',
    market: { at: `${latest}T19:00:00+08:00`, date: latest, timezone: 'Asia/Shanghai', trading_day: true, next_trading_day: '2026-11-18' },
    next: date === latest ? null : latest, status: date === latest ? 'live' : 'archive', archived: date !== latest,
    cached: true, issues: [], previous_close: 3560, previous_close_date: previous, etf_count: 1,
    symbols: ['510300.SH', '159915.SZ'],
    names: { '510300.SH': '华泰柏瑞沪深300ETF', '159915.SZ': '易方达创业板ETF' },
    turnover_baseline: { status: 'unavailable' },
    points: [
      { minute: '09:30', turnover_cny: 100_000_000, index_close: 3572, etf_count: 1 },
      { minute: '14:59', turnover_cny: 150_000_000, index_close: 3599, etf_count: 1 },
    ],
  }
}
function Location() {
  return <p data-testid="search">{useLocation().search}</p>
}
function show(path = '/etf') {
  return render(<MemoryRouter initialEntries={[path]}><BroadEtf /><Location /></MemoryRouter>)
}

beforeEach(() => {
  localStorage.clear()
  load.mockReset()
  reference.mockReset().mockResolvedValue(null)
  chartBreadth.mockClear()
  startBackfill.mockReset()
  stats.mockReset().mockImplementation(async date => ({
    date, breadth: { through: '15:00', points: {} },
    daily_flow: { total: 22, covered: 0, status: 'pending', net_cny: null },
  }))
  load.mockImplementation(async date => session(date || latest))
})
afterEach(() => { cleanup(); vi.useRealTimers() })

describe('Tushare broad-market ETFs', () => {
  it('shows finished minutes on timed polls without replacing chart data for progress-only updates', async () => {
    const seed: EtfMarketStats = {
      date: latest, breadth: { through: '09:31', points: {} },
      daily_flow: { total: 22, covered: 22, status: 'ready', net_cny: 0 },
    }
    const early = { up: 10, down: 20, flat: 3, source: 'backfill' as const }
    stats.mockResolvedValueOnce(seed).mockResolvedValueOnce({
      ...seed, backfill: { status: 'running', total: 55, processed: 3, added: 0, reason: null },
    }).mockResolvedValueOnce({
      ...seed, backfill: { status: 'running', total: 55, processed: 40, added: 1, reason: null },
      breadth: { through: '09:31', points: { '09:30': early } },
    }).mockResolvedValueOnce({
      ...seed, backfill: { status: 'running', total: 55, processed: 54, added: 1, reason: null },
      breadth: { through: '09:31', points: { '09:30': { ...early } } },
    }).mockResolvedValue({
      ...seed, backfill: { status: 'complete', total: 55, processed: 55, added: 2, reason: null },
      breadth: { through: '09:31', points: { '09:30': early, '09:31': { ...early, up: 11 } } },
    })
    startBackfill.mockResolvedValue({ date: latest, status: 'running' })
    show(`/etf?date=${latest}`)
    const button = await screen.findByRole('button', { name: '回补' }) as HTMLButtonElement
    expect(startBackfill).not.toHaveBeenCalled()
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    await act(async () => { fireEvent.click(button) })
    expect(startBackfill).toHaveBeenCalledOnce()
    expect(startBackfill).toHaveBeenCalledWith(latest)
    expect(screen.getByText('回补中 3 / 55 只')).toBeTruthy()
    expect(button.disabled).toBe(true)
    await act(async () => { await vi.advanceTimersByTimeAsync(3999) })
    expect(stats).toHaveBeenCalledTimes(2)
    await act(async () => { await vi.advanceTimersByTimeAsync(1) })
    expect(screen.getByText('回补中 40 / 55 只 · 已补 1 分钟')).toBeTruthy()
    const chart = screen.getByRole('img', { name: latest })
    expect(chart.getAttribute('data-breadth')).toContain('09:30')
    expect(chart.getAttribute('data-breadth')).not.toContain('09:31')
    const drawn = chartBreadth.mock.lastCall?.[0]
    await act(async () => { await vi.advanceTimersByTimeAsync(4000) })
    expect(screen.getByText('回补中 54 / 55 只 · 已补 1 分钟')).toBeTruthy()
    expect(chartBreadth.mock.lastCall?.[0]).toBe(drawn)
    await act(async () => { await vi.advanceTimersByTimeAsync(4000) })
    expect(screen.getByText('已回补 2 分钟')).toBeTruthy()
    expect(chart.getAttribute('data-breadth')).toContain('09:31')
    expect(screen.queryByRole('button', { name: '回补' })).toBeNull()
    expect(load).toHaveBeenCalledTimes(1)
  })

  it('loads the selected date’s stored breadth and only shows a complete net flow', async () => {
    stats.mockImplementation(async date => ({
      date,
      breadth: { through: '15:00', points: date === latest ? { '09:33': { up: 1200, down: 800, flat: 20 } } : {} },
      daily_flow: date === latest
        ? { status: 'partial', total: 22, covered: 21, net_cny: null }
        : { status: 'ready', total: 22, covered: 22, net_cny: -250_000_000 },
    }))
    show()
    expect(await screen.findByText('份额覆盖 21 / 22 只')).toBeTruthy()
    expect(screen.getByText('22 只 ETF · 全天净申赎')).toBeTruthy()
    expect(screen.getByRole('img', { name: latest }).getAttribute('data-breadth')).toContain('09:33')
    fireEvent.click(screen.getByRole('button', { name: '前一日期' }))
    expect(await screen.findByText('-2.5')).toBeTruthy()
    expect(stats).toHaveBeenLastCalledWith(previous, expect.any(AbortSignal))
    expect(screen.getByRole('img', { name: previous }).getAttribute('data-breadth')).toBe('{}')
  })

  it('uses each ETF’s first available minute so different price levels do not change the displayed move', () => {
    const cheap = etfIntradayMove({ '09:30': 1, '09:32': 1.02 })
    const expensive = etfIntradayMove({ '09:31': 10, '09:32': 10.2 })
    expect(cheap?.baseMinute).toBe('09:30')
    expect(cheap?.values.slice(0, 2)).toEqual([0, null])
    expect(expensive?.baseMinute).toBe('09:31')
    expect(expensive?.values.slice(0, 2)).toEqual([null, 0])
    expect(cheap?.values[2]).toBeCloseTo(.02)
    expect(expensive?.values[2]).toBeCloseTo(.02)
  })

  it('switches by date and uses the archived result without a refresh action', async () => {
    show()
    expect(await screen.findByRole('img', { name: latest })).toBeTruthy()
    expect(screen.getByText('2.5')).toBeTruthy()
    expect(screen.getByText('部分分钟成交缺失')).toBeTruthy()
    expect(reference).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '前一日期' }))
    expect(await screen.findByRole('img', { name: previous })).toBeTruthy()
    expect(screen.getByTestId('search').textContent).toBe(`?date=${previous}`)
    expect(load).toHaveBeenLastCalledWith(previous, false, expect.any(AbortSignal))
    expect(screen.queryByRole('button', { name: '刷新行情' })).toBeNull()
    expect(screen.queryByRole('link', { name: '国家队追踪' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: '最新交易日' }))
    expect(await screen.findByRole('img', { name: latest })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '刷新行情' }))
    await waitFor(() => expect(load).toHaveBeenLastCalledWith('', true, expect.any(AbortSignal)))
  })

  it('supports keyboard resizing and stores the sidebar preference without reloading prices', async () => {
    show()
    await screen.findByRole('img', { name: latest })
    fireEvent.keyDown(screen.getByRole('separator', { name: '调整侧栏宽度' }), { key: 'ArrowRight' })
    expect(screen.getByRole('separator').getAttribute('aria-valuenow')).toBe('232')
    fireEvent.click(screen.getByRole('button', { name: '收起侧栏' }))
    expect(screen.getByRole('button', { name: '展开侧栏' }).getAttribute('aria-expanded')).toBe('false')
    expect(screen.queryByRole('separator')).toBeNull()
    expect(localStorage.getItem('panwatch_etf_sidebar_width')).toBe('232')
    expect(localStorage.getItem('panwatch_etf_sidebar_collapsed')).toBe('true')
    fireEvent.click(screen.getByRole('button', { name: '展开侧栏' }))
    expect(screen.getByRole('separator').getAttribute('aria-valuenow')).toBe('232')
    expect(load).toHaveBeenCalledTimes(1)
  })

  it('compares cumulative turnover with the historical average at the same minute', async () => {
    const result = session()
    load.mockResolvedValue({ ...result, etf_count: 2, turnover_baseline: { status: 'needs_calculation' }, points: [
      { ...result.points[0], etf_count: 2 },
      { ...result.points[1], etf_count: 2, minute: '09:31' },
    ] })
    let resolveBaseline!: (value: EtfTurnoverBaseline) => void
    reference.mockReturnValue(new Promise(resolve => { resolveBaseline = resolve }))
    show()
    expect(await screen.findByText('计算中')).toBeTruthy()
    expect(screen.getByRole('img', { name: latest })).toBeTruthy()
    expect(screen.getByText('前 5 个交易日同分钟均值')).toBeTruthy()
    await act(async () => { resolveBaseline({ sessions: 5, cumulative_cny: { '09:31': 200_000_000, '15:00': 500_000_000 } }) })
    expect(await screen.findByText('较同期均值高 25%')).toBeTruthy()
    expect(screen.queryByText('计算中')).toBeNull()
    expect(screen.getByText('明显放量')).toBeTruthy()
    expect(screen.getByText('对比前 5 个交易日同期均值 · 截至 09:31')).toBeTruthy()
    expect(screen.getByText('前 5 个交易日同分钟均值')).toBeTruthy()
  })

  it('renders cached averages together with each date without starting a calculation request', async () => {
    load.mockImplementation(async date => {
      const result = session(date || latest)
      return { ...result, etf_count: 2, points: [
        { ...result.points[0], etf_count: 2 },
        { ...result.points[1], etf_count: 2, minute: '09:31' },
      ], turnover_baseline: { status: 'ready', value: {
        sessions: 5, cumulative_cny: { '09:31': result.date === latest ? 200_000_000 : 500_000_000 },
      } } }
    })
    show()
    expect(await screen.findByText('较同期均值高 25%')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '前一日期' }))
    expect(await screen.findByRole('img', { name: previous })).toBeTruthy()
    expect(screen.getByText('较同期均值低 50%')).toBeTruthy()
    expect(screen.queryByText('计算中')).toBeNull()
    expect(reference).not.toHaveBeenCalled()
  })

  it('separates the index and ETF catalogs and restores checked lines from both tabs', async () => {
    if (typeof ResizeObserver === 'undefined') vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
    const coal = { symbol: '515220.SH', name: '国泰中证煤炭ETF' }
    const power = { symbol: '159611.SZ', name: '广发中证全指电力ETF' }
    const chip = { symbol: '159325.SZ', name: '南方中证半导体行业精选ETF' }
    const star = { symbol: '000688.SH', name: '科创50', kind: 'index' as const }
    const composite = { symbol: '000001.SH', name: '上证指数', kind: 'index' as const }
    const catalog = vi.mocked(etfApi.priceCatalog)
    catalog.mockClear().mockImplementation(async (_, kind) => ({
      items: kind === 'index' ? [star, composite] : [coal, power, chip], issue: null,
    }))
    const prices = vi.mocked(etfApi.priceLine)
    prices.mockClear().mockImplementation(async (date, symbol, _, kind) => ({
      date, symbol, kind, closes: { '09:30': 1.23 }, complete: true, issue: null,
    }))
    show(`/etf?date=${previous}`)
    const chart = await screen.findByRole('img', { name: previous })
    const openPicker = () => fireEvent.click(screen.getByRole('button', { name: '选择波动线' }))
    const tab = (label: string) => fireEvent.keyDown(screen.getByRole('tab', { name: label }), { key: 'Enter' })
    const checkbox = (fund: EtfPriceInstrument) => screen.getByRole('checkbox', { name: `${fund.name} ${fund.symbol}` }) as HTMLInputElement
    const checklist = () => within(screen.getByRole('list', { name: '波动线选项' }))
    openPicker()
    expect(await screen.findByText('全部 3 只 ETF')).toBeTruthy()
    expect(screen.getAllByRole('checkbox')).toHaveLength(3)
    expect(checkbox(coal).checked).toBe(false)
    expect(checklist().queryByRole('heading')).toBeNull()
    expect(checklist().queryByRole('separator')).toBeNull()
    expect(prices).not.toHaveBeenCalled()
    const input = screen.getByRole('searchbox', { name: '搜索 ETF 名称或代码' })
    async function choose(query: string, fund: EtfPriceInstrument) {
      fireEvent.change(input, { target: { value: query } })
      expect(screen.getAllByRole('checkbox')).toHaveLength(1)
      fireEvent.click(checkbox(fund))
      await waitFor(() => expect(chart.getAttribute('data-price')).toContain(fund.symbol))
    }
    await choose('煤炭', coal)
    fireEvent.change(input, { target: { value: 'ETF' } })
    expect(screen.getAllByRole('checkbox')).toEqual([checkbox(coal), checkbox(chip), checkbox(power)])
    expect(checklist().getByRole('heading', { name: '已选 1' })).toBeTruthy()
    expect(checklist().getByRole('separator').closest('li')?.previousElementSibling?.contains(checkbox(coal))).toBe(true)
    await choose('159611', power)
    await choose('159325', chip)
    expect(catalog).toHaveBeenCalledTimes(1)
    expect(chart.getAttribute('data-price')).toBe([coal.symbol, power.symbol, chip.symbol].join(','))
    fireEvent.change(input, { target: { value: '' } })
    expect(checkbox(coal).checked && checkbox(power).checked && checkbox(chip).checked).toBe(true)
    expect(checklist().getByRole('heading', { name: '已选 3' })).toBeTruthy()
    expect(checklist().queryByRole('separator')).toBeNull()
    const toggleCoal = () => fireEvent.click(checkbox(coal))
    toggleCoal()
    expect(screen.getAllByRole('checkbox')).toEqual([checkbox(chip), checkbox(power), checkbox(coal)])
    expect(checklist().getByRole('heading', { name: '已选 2' })).toBeTruthy()
    expect(chart.getAttribute('data-price')).toBe([power.symbol, chip.symbol].join(','))
    expect(screen.getByRole('group', { name: '当前显示的波动线' }).textContent).not.toContain(coal.name)
    toggleCoal()
    expect(chart.getAttribute('data-price')).toBe([coal.symbol, power.symbol, chip.symbol].join(','))
    expect(prices).toHaveBeenCalledTimes(3)
    toggleCoal()
    tab('指数')
    expect(await screen.findByText('全部 2 个沪深指数')).toBeTruthy()
    expect(screen.getAllByRole('checkbox')).toEqual([checkbox(composite), checkbox(star)])
    const indexSearch = screen.getByRole('searchbox', { name: '搜索指数名称或代码' })
    fireEvent.change(indexSearch, { target: { value: '000688' } })
    fireEvent.click(checkbox(star))
    await waitFor(() => expect(chart.getAttribute('data-price')).toBe([power.symbol, chip.symbol, star.symbol].join(',')))
    fireEvent.change(indexSearch, { target: { value: '' } })
    expect(screen.getAllByRole('checkbox')).toEqual([checkbox(star), checkbox(composite)])
    expect(checklist().getByRole('heading', { name: '已选 1' })).toBeTruthy()
    expect(checklist().getByRole('separator').closest('li')?.nextElementSibling?.contains(checkbox(composite))).toBe(true)
    expect(prices).toHaveBeenLastCalledWith(previous, star.symbol, expect.any(AbortSignal), 'index')
    tab('ETF')
    expect(await screen.findByText('全部 3 只 ETF')).toBeTruthy()
    expect(checkbox(power).checked && checkbox(chip).checked).toBe(true)
    expect(catalog).toHaveBeenCalledTimes(2)
    cleanup()
    show(`/etf?date=${previous}`)
    const reopened = await screen.findByRole('img', { name: previous })
    await waitFor(() => expect(reopened.getAttribute('data-price')).toBe([power.symbol, chip.symbol, star.symbol].join(',')))
    openPicker()
    expect(await screen.findByText('全部 3 只 ETF')).toBeTruthy()
    expect(checkbox(coal).checked).toBe(false)
    expect(checkbox(power).checked && checkbox(chip).checked).toBe(true)
    tab('指数')
    expect(await screen.findByRole('checkbox', { name: /科创50/ })).toBeTruthy()
    expect(checkbox(star).checked).toBe(true)
    expect(catalog).toHaveBeenCalledTimes(2)
    expect(prices).toHaveBeenCalledTimes(7)
  })

  it('keeps the active line from saved single-line preferences', async () => {
    if (typeof ResizeObserver === 'undefined') vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
    const coal = { symbol: '515220.SH', name: '国泰中证煤炭ETF' }
    localStorage.setItem('panwatch_etf_price_lines', JSON.stringify({ items: [coal], active: coal.symbol }))
    vi.mocked(etfApi.priceLine).mockImplementation(async (date, symbol) => ({
      date, symbol, closes: { '09:30': 1.25 }, complete: true, issue: null,
    }))
    show(`/etf?date=${previous}`)
    const chart = await screen.findByRole('img', { name: previous })
    await waitFor(() => expect(chart.getAttribute('data-price')).toBe(coal.symbol))
    expect(JSON.parse(localStorage.getItem('panwatch_etf_price_lines')!)).toEqual({ items: [coal], visible: [coal.symbol] })
  })

  it('aligns visible refresh to minute bars, adapts to a late bar and stops on historical dates', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(`${latest}T09:33:58+08:00`))
    load.mockImplementation(async date => {
      const result = session(date || latest)
      return { ...result, market: { ...result.market, at: new Date().toISOString() },
        turnover_baseline: { status: 'needs_calculation' },
        points: [{ minute: load.mock.calls.length >= 3 ? '09:35' : '09:33',
          turnover_cny: 100_000_000, index_close: 3550, etf_count: 2 }] }
    })
    await act(async () => { show() })
    expect(screen.getByText('盘中')).toBeTruthy()
    expect(screen.getByText('09:33:58')).toBeTruthy()
    await act(async () => { await vi.advanceTimersByTimeAsync(13_999) })
    expect(load).toHaveBeenCalledTimes(1)
    await act(async () => { await vi.advanceTimersByTimeAsync(1) })
    expect(load).toHaveBeenCalledTimes(2)
    expect(load).toHaveBeenLastCalledWith('', true, expect.any(AbortSignal))
    expect(screen.getByText('09:33:58')).toBeTruthy()
    await act(async () => { await vi.advanceTimersByTimeAsync(65_999) })
    expect(load).toHaveBeenCalledTimes(2)
    await act(async () => { await vi.advanceTimersByTimeAsync(1) })
    expect(load).toHaveBeenCalledTimes(3)
    expect(screen.getByText('09:35:18')).toBeTruthy()
    expect(reference).toHaveBeenCalledTimes(1)
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: '前一日期' })) })
    expect(load).toHaveBeenCalledTimes(4)
    await act(async () => { await vi.advanceTimersByTimeAsync(120_000) })
    expect(load).toHaveBeenCalledTimes(4)
  })

  it('schedules the final bars and skips the lunch break and market holidays', () => {
    const market = session().market
    const at = (time: string) => Date.parse(`${latest}T${time}+08:00`)
    const next = (time: string) => nextEtfRefresh(at(time), market, '', 12_000, undefined, undefined)
    expect(marketPhase(at('09:29:59'), latest, market)).toBe('marketPreopen')
    expect(next('11:30:05')).toMatchObject({ minute: '11:30', at: at('11:30:32') })
    expect(next('11:45:00')).toMatchObject({ minute: '13:01', at: at('13:01:12') })
    expect(marketPhase(at('15:00:00'), latest, market)).toBe('marketClosed')
    expect(next('15:00:00')).toMatchObject({ minute: '15:00', at: at('15:00:32') })
    expect(next('15:02:00')).toMatchObject({ day: '2026-11-18', minute: '09:30' })
    expect(marketPhase(at('10:00:00'), latest, { ...market, trading_day: false })).toBe('marketHoliday')
    expect(nextEtfRefresh(at('10:00:00'), { ...market, trading_day: false }, '', 12_000, undefined, undefined))
      .toMatchObject({ day: '2026-11-18', minute: '09:30' })
  })

  it('refreshes stored breadth even when the main chart already has the latest ETF minute', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(`${latest}T09:34:18+08:00`))
    const readyMinute = '09:35'
    load.mockImplementation(async () => {
      const result = session()
      return { ...result, market: { ...result.market, at: new Date().toISOString() },
        points: ['09:34', readyMinute].map(minute => ({
          minute, turnover_cny: 100_000_000, index_close: 3550, etf_count: 2,
        })) }
    })
    const flow = { total: 22, covered: 0, status: 'pending' as const, net_cny: null }
    stats.mockResolvedValueOnce({ date: latest, breadth: { through: '09:34', points: {} }, daily_flow: flow })
      .mockResolvedValue({ date: latest, breadth: { through: readyMinute, points: {
        [readyMinute]: { up: 2000, down: 1800, flat: 120 },
      } }, daily_flow: flow })

    await act(async () => { show(`/etf?date=${latest}`) })
    const chart = screen.getByRole('img', { name: latest })
    expect(chart.getAttribute('data-breadth')).toBe('{}')
    expect(stats).toHaveBeenCalledTimes(1)
    await act(async () => { await vi.advanceTimersByTimeAsync(59_999) })
    expect(stats).toHaveBeenCalledTimes(1)
    await act(async () => { await vi.advanceTimersByTimeAsync(1) })
    expect(stats).toHaveBeenCalledTimes(2)
    expect(load).toHaveBeenCalledTimes(1)
    expect(chart.getAttribute('data-breadth')).toContain(readyMinute)
  })

  it('shows names and codes in both sample groups and links verified disclosures', async () => {
    const report = 'https://www.sse.com.cn/report.pdf'
    load.mockResolvedValue({ ...session(), disclosures: {
      '510300.SH': { report_date: '2025-12-31', url: report },
    } })
    show()
    fireEvent.click(screen.getByText('数据来源与统计口径'))
    await screen.findByText('ETF 样本（2 只）')
    expect(screen.getByRole('link', { name: '华泰柏瑞沪深300ETF 510300.SH' }).getAttribute('href')).toBe(report)
    expect(screen.getByText('易方达创业板ETF').closest('li')?.textContent).toContain('159915.SZ')
  })

  it('shows configuration and retry when the source key is unavailable', async () => {
    load.mockResolvedValue({ ...session(), points: [], issues: ['key_required'] })
    show()
    expect((await screen.findByRole('alert')).textContent).toContain('请检查 Tushare Token 是否已配置且有效。')
    expect(screen.getByRole('link', { name: '打开 Tushare 配置' }).getAttribute('href')).toBe('/settings#sec-data-providers')
    expect(screen.queryByRole('img', { name: latest })).toBeNull()
    expect(screen.getByRole('img', { name: 'breadth' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '重试' })).toBeTruthy()
  })
})
