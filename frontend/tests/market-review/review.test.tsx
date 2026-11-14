import { beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import i18n from '@/i18n'
import MarketReview from '@/pages/MarketReview'
import { clock, ladderRows, type LimitBoard } from '@/components/market-review/data'
import { Ladder, LimitList, StockDetail } from '@/components/market-review/LimitPanels'
import { useReview } from '@/components/market-review/use-review'
import { SourceNote, ReviewOverview } from '@/components/market-review/ReviewOverview'
import { fetchAPI } from '@panwatch/api'

vi.mock('@panwatch/api', () => ({ fetchAPI: vi.fn() }))
const board: LimitBoard = {
  date: '2026-11-12', market_status: '已收盘', available: true, total_count: 3, active_count: 2, opened_count: 1, seal_rate: 67, observed_at: '2026-11-12T15:05:00+08:00',
  stocks: [{ code: '600001', name: '封板甲', active: true, board_count: 3, group: '机器人', change_percent: 10, themes: ['减速器'], amount: 200000000 },
    { code: '600002', name: '炸板乙', active: false, board_count: 1, broken_board: 3, group: '机器人', change_percent: -2, themes: ['机械'] },
    { code: '600003', name: '首板丙', active: true, board_count: 1, group: '消费', change_percent: 9.99 }],
  fallen: [{ code: '600004', name: '断板丁', board: 3, change_percent: -7 }], waiting: [], watch: [{ code: '600005', name: '待晋级戊', change_percent: 2 }], history: [], promotion: [],
}
beforeEach(async () => { cleanup(); vi.clearAllMocks(); await i18n.loadNamespaces('marketReview') })
const wrap = (ui: React.ReactNode) => render(<MemoryRouter>{ui}</MemoryRouter>)

describe('market review', () => {
  it('shows failed promotions at their attempted height without inflating sealed counts', () => {
    const rows = ladderRows(board)
    expect(rows[0].height).toBe(3)
    expect(rows[0].sealed).toBe(1)
    expect(rows[0].stocks.map(s => s.state)).toEqual(['sealed', 'opened', 'fallen'])
    expect(rows[1].height).toBe(2)
    expect(rows[1].stocks[0].state).toBe('waiting')
  })
  it('uses exchange time for UTC and offset timestamps', () => {
    expect(clock('2026-11-12T07:05:00Z')).toBe('15:05')
    expect(clock('2026-11-12T15:05:00+08:00')).toBe('15:05')
    expect(clock('bad')).toBe('—')
    expect(clock('09:35')).toBe('09:35')
    expect(clock('25:99')).toBe('—')
  })
  it('searches catalysts and opens the matching actual stock', () => {
    const open = vi.fn()
    wrap(<Ladder board={board} onOpen={open} query="减速器" />)
    expect(screen.queryByText('炸板乙')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /封板甲/ }))
    expect(open.mock.calls[0][0].code).toBe('600001')
  })
  it('supports details sorting and empty search', () => {
    const props = { board, onOpen: vi.fn(), view: 'details', onView: vi.fn(), query: '' }
    const page = wrap(<LimitList {...props} />)
    fireEvent.click(screen.getByRole('button', { name: /涨跌幅/ }))
    expect(screen.getAllByRole('row')[1].textContent).toContain('封板甲')
    fireEvent.click(screen.getByRole('button', { name: /涨跌幅/ }))
    expect(screen.getAllByRole('row')[1].textContent).toContain('炸板乙')
    page.rerender(<MemoryRouter><LimitList {...props} query="不存在" /></MemoryRouter>)
    expect(screen.getByText('没有匹配的股票')).toBeTruthy()
  })
  it('keeps unavailable financial fields distinct from zero in the stock dialog', () => {
    render(<StockDetail stock={board.stocks[0]} date={board.date} onClose={vi.fn()} />)
    expect(screen.getByRole('dialog')).toBeTruthy()
    expect(screen.getByText('暂无分时数据')).toBeTruthy()
    expect(screen.getAllByText('—').length).toBeGreaterThan(3)
  })
  it('discards late results when the trading date changes', async () => {
    let resolveOld!: (value: unknown) => void
    vi.mocked(fetchAPI).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve })).mockResolvedValueOnce({ payload: { date: '2026-11-11' }, stale: false })
    function Probe({ date }: { date: string }) { const state = useReview<LimitBoard>('board', date); return <span>{state.data?.payload.date ?? 'loading'}</span> }
    const page = render(<Probe date="2026-11-12" />)
    page.rerender(<Probe date="2026-11-11" />)
    await screen.findByText('2026-11-11')
    resolveOld({ payload: { date: '2026-11-12' }, stale: false })
    await waitFor(() => expect(screen.queryByText('2026-11-12')).toBeNull())
  })
})


it('replaces the full page ladder when searching and clearing without leaving old rows', async () => {
  vi.mocked(fetchAPI).mockImplementation(async path => ({ payload: String(path).includes('/dates') ? ['2026-11-12', '2026-11-11'] : board, stale: false, source: 'eastmoney+tencent' }))
  render(<MemoryRouter initialEntries={['/limit-up']}><MarketReview /></MemoryRouter>)
  await screen.findByRole('textbox', { name: '搜索股票、代码或行业' })
  fireEvent.change(screen.getByRole('textbox', { name: '搜索股票、代码或行业' }), { target: { value: '封板甲' } })
  await waitFor(() => expect(screen.queryByText('炸板乙')).toBeNull())
  expect(document.querySelectorAll('.review-ladder').length).toBe(1)
  fireEvent.click(screen.getByRole('button', { name: '清除搜索' }))
  await waitFor(() => expect(document.querySelectorAll('.review-ladder').length).toBe(1))
  expect(screen.getAllByText('炸板乙').length).toBe(2)
})


it('labels independent providers and keeps missing ETF baseline distinct from zero', async () => {
  vi.mocked(fetchAPI).mockImplementation(async path => ({ payload: String(path).includes('/etf') ? {
    date: '2026-11-12', amount: 100, minutes: [['10:00', 100]], windows: [], peak_window: null,
    errors: { baseline: 'unavailable' }, sources: [{ id: 'tencent', name: '腾讯证券', url: 'https://gu.qq.com/' }], method: 'etf_turnover',
  } : String(path).includes('/daily') ? { lhb: null, futures: null } : {
    industry: { sectors: [] }, indicators: { commodities: { items: [] }, groups: [] },
  }, stale: false }))
  wrap(<ReviewOverview board={board} onOpen={vi.fn()} refresh={0} onRetry={vi.fn()} />)
  expect(await screen.findByText('20日同期成交额基准暂缺')).toBeTruthy()
  expect(screen.getByRole('link', { name: '腾讯证券' }).getAttribute('href')).toBe('https://gu.qq.com/')
  expect(screen.queryByText('0.0倍')).toBeNull()
  expect(document.querySelector('a[href*="kanpanba"]')).toBeNull()
})

it('explains sector ETF methodology instead of presenting custom baskets as identical', () => {
  render(<SourceNote data={{ sources: [{ id: 'tencent', name: '腾讯证券', url: 'https://gu.qq.com/' }], method: 'sector_etfs' }} />)
  expect(screen.getByText(/以公开ETF代表行业与主题表现/)).toBeTruthy()
})
