import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import BroadEtf from '@/pages/BroadEtf'
import { etfApi, type EtfBoard, type EtfNationalTeam, type EtfHistory } from '@panwatch/api/etf'
import i18n from '@/i18n'

vi.mock('@panwatch/api/etf', () => ({ etfApi: { board: vi.fn(), dates: vi.fn(), national: vi.fn(), history: vi.fn() } }))

function board(date = '2026-11-13'): EtfBoard {
  return { date, status: '收盘', amount: 10, net: 4, net20: 30, covered: 1, shares_published: true, shares_final: true,
    updated_at: '2026-11-14T08:00:00+08:00', hs300_change_percent: -1, signal: { kind: 'quiet', title: '', detail: '' },
    etfs: [{ code: '510300', name: '沪深300ETF华泰柏瑞', index: '沪深300', manager: '华泰柏瑞', change_percent: -1,
      amount: 10, close: 4, net: 4, net20: 30, shares_delta: 1, scale: 400, peak_window: null }],
    minutes: [['09:31', 1], ['09:32', 3]], profile: [['09:31', 2], ['09:32', 4]], cumulative: [['09:32', 4, 6, .67]],
    windows: [], series: [{ date, net: 4, hs300: 4000, hs300_change_percent: -1, covered: 1, peak_window: null }], surges: [] }
}

const national: EtfNationalTeam = { date: '2026-11-13', holdings: [{ holder_name: '中央汇金投资有限责任公司', institution: 'huijin',
  code: '510300', name: '沪深300ETF华泰柏瑞', index: '沪深300', report_date: '2025-12-31', previous_report_date: null,
  shares: 100000000, ratio_percent: 25, shares_change: null, known_from: '2026-11-15T00:00:00Z', announced_at: null,
  source_url: 'https://example.com/report', snapshot_id: 1 }], institutions: ['huijin'], holding_etf_count: 1,
  watchlist: [{ ...board().etfs[0], disclosed_ratio: 25 }], watchlist_net_estimate_cny: 400000000, signals: [],
  coverage: [{ code: '510300', report_date: '2025-12-31' }], stale: false }

function history(): EtfHistory {
  return { range: { start: '2026-08-13', end: '2026-11-13' }, period: '3m', scope: 'market',
    available_start: '2026-03-02', available_end: '2026-11-13', collecting: false, stale: false,
    series: ['2026-11-12', '2026-11-13'].map((date, i) => ({ date, net: i ? 4 : -2, amount: 10, scale: 400,
      cumulative_net: i ? 2 : -2, cumulative_net_days: i + 1, hs300: 4000, hs300_change_percent: -1, peak_ratio: 1, covered: 1, expected: 1, snapshot_ids: [1] })),
    summary: { net: 2, inflow: 4, outflow: -2, amount: 20, days: 2, net_days: 2, amount_days: 2, aggregation: 'available_observations', missing_net_dates: [], missing_amount_dates: [], loaded_days: 2, funds: 1, coverage_min: 1, coverage_max: 1 },
    universe: [{ code: '510300', name: '沪深300ETF华泰柏瑞' }],
    funds: [{ code: '510300', name: '沪深300ETF华泰柏瑞', index: '沪深300', net: 2, amount: 20, scale: 400, as_of: '2026-11-13', days: 2, amount_days: 2, expected_days: 2 }],
    holdings_trend: [{ date: '2025-12-31', shares: 1, reported_shares: 1, held_funds: 1, reported_funds: 1, expected_funds: 1, before_range: true, snapshot_ids: [2] }],
    disclosures: national.holdings, signals: [], flow_attribution: 'all_etf_investors', composition_mode: 'broad_market' }
}

beforeEach(async () => {
  await i18n.loadNamespaces('etf')
  vi.clearAllMocks()
  vi.mocked(etfApi.board).mockImplementation(async date => ({ payload: board(date || undefined), stale: false, snapshot_id: 1, observed_at: '' }))
  vi.mocked(etfApi.dates).mockResolvedValue(['2026-11-13', '2026-11-12'])
  vi.mocked(etfApi.national).mockResolvedValue(national)
  vi.mocked(etfApi.history).mockResolvedValue(history())
})

describe('broad-market ETF dashboard', () => {
  it('preserves daily market data and trading-date navigation', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter initialEntries={['/etf?view=daily']}><BroadEtf /></MemoryRouter>)
    await screen.findByRole('img', { name: '分钟成交' })
    expect(etfApi.national).not.toHaveBeenCalled()
    await user.click(screen.getByText('1只ETF明细'))
    expect(screen.getAllByText('510300').length).toBeGreaterThan(0)
    await user.click(screen.getByRole('button', { name: '前一交易日' }))
    await waitFor(() => expect(etfApi.board).toHaveBeenCalledWith('2026-11-12', expect.any(AbortSignal)))
    await waitFor(() => expect(screen.getByRole('button', { name: '前一交易日' }).hasAttribute('disabled')).toBe(true))
  })

  it('loads named holdings separately and preserves the reporting date', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter initialEntries={['/etf']}><BroadEtf /></MemoryRouter>)
    await user.click(screen.getByRole('tab', { name: '国家队追踪' }))
    await screen.findByRole('img', { name: '持有份额' })
    await user.click(screen.getAllByRole('tab', { name: '日数据' })[1])
    await screen.findByText('中央汇金投资有限责任公司')
    expect(screen.getByText('2025-12-31')).toBeTruthy()
    expect(screen.getByText('持仓ETF净申赎估算')).toBeTruthy()
    expect(screen.queryByText('国家队今日买入')).toBeNull()
    expect(screen.getByText('暂无逆势申购信号')).toBeTruthy()
  })

  it('offers retry when market data fails without inventing values', async () => {
    vi.mocked(etfApi.board).mockRejectedValueOnce(new Error('offline'))
    const user = userEvent.setup()
    render(<MemoryRouter initialEntries={['/etf?view=daily']}><BroadEtf /></MemoryRouter>)
    await screen.findByRole('alert')
    await user.click(screen.getByRole('button', { name: '重试' }))
    await screen.findByRole('img', { name: '分钟成交' })
  })

  it('supports keyboard inspection of minute data', async () => {
    render(<MemoryRouter initialEntries={['/etf?view=daily']}><BroadEtf /></MemoryRouter>)
    const chart = await screen.findByRole('img', { name: '分钟成交' })
    fireEvent.keyDown(chart, { key: 'ArrowLeft' })
    expect(screen.getByText('09:31')).toBeTruthy()
  })

  it('defaults to three-month history and switches to a custom interval', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter initialEntries={['/etf']}><BroadEtf /></MemoryRouter>)
    await screen.findByRole('img', { name: '区间累计净申赎' })
    expect(etfApi.history).toHaveBeenLastCalledWith(expect.objectContaining({ period: '3m', scope: 'market' }), expect.any(AbortSignal))
    expect(etfApi.board).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: '近1月' }))
    await waitFor(() => expect(etfApi.history).toHaveBeenLastCalledWith(expect.objectContaining({ period: '1m' }), expect.any(AbortSignal)))
    await user.click(screen.getByRole('button', { name: '自定义' }))
    fireEvent.change(screen.getByLabelText('开始日期'), { target: { value: '2026-10-01' } })
    fireEvent.change(screen.getByLabelText('结束日期'), { target: { value: '2026-10-30' } })
    await user.click(screen.getByRole('button', { name: '应用' }))
    await waitFor(() => expect(etfApi.history).toHaveBeenLastCalledWith(expect.objectContaining({ period: 'custom', start: '2026-10-01', end: '2026-10-30' }), expect.any(AbortSignal)))
    const calls = vi.mocked(etfApi.history).mock.calls.length
    fireEvent.change(screen.getByLabelText('开始日期'), { target: { value: '2026-11-01' } })
    await user.click(screen.getByRole('button', { name: '应用' }))
    expect(screen.getByRole('alert').textContent).toContain('请选择有效的起止日期')
    expect(etfApi.history).toHaveBeenCalledTimes(calls)
  })

  it('opens a historical day by keyboard and retains the chosen range on return', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter initialEntries={['/etf?period=6m']}><BroadEtf /></MemoryRouter>)
    const chart = await screen.findByRole('img', { name: '净申赎估算' })
    fireEvent.keyDown(chart, { key: 'ArrowLeft' })
    fireEvent.keyDown(chart, { key: 'Enter' })
    await waitFor(() => expect(etfApi.board).toHaveBeenLastCalledWith('2026-11-12', expect.any(AbortSignal)))
    await screen.findByRole('img', { name: '分钟成交' })
    await user.click(screen.getByRole('tab', { name: '总览' }))
    await screen.findByRole('img', { name: '净申赎估算' })
    expect(screen.getByRole('button', { name: '近半年' }).getAttribute('aria-pressed')).toBe('true')
  })

  it('keeps national history filters when drilling into daily holdings', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter initialEntries={['/etf?view=national&period=all&institution=huijin&code=510300']}><BroadEtf /></MemoryRouter>)
    const chart = await screen.findByRole('img', { name: '净申赎估算' })
    expect(etfApi.history).toHaveBeenLastCalledWith(expect.objectContaining({ period: 'all', scope: 'national', code: '510300', institution: 'huijin' }), expect.any(AbortSignal))
    expect(screen.getByText('区间前最近披露')).toBeTruthy()
    fireEvent.keyDown(chart, { key: 'Enter' })
    await screen.findByText('中央汇金投资有限责任公司')
    expect(etfApi.national).toHaveBeenCalledWith('2026-11-13', expect.any(AbortSignal))
    await user.click(screen.getByRole('tab', { name: '历史趋势' }))
    await screen.findByRole('img', { name: '持有份额' })
    expect(screen.getByRole('button', { name: '全部', exact: true }).getAttribute('aria-pressed')).toBe('true')
  })

  it('recovers a failed historical query using retry', async () => {
    vi.mocked(etfApi.history).mockRejectedValueOnce(new Error('offline'))
    const user = userEvent.setup()
    render(<MemoryRouter><BroadEtf /></MemoryRouter>)
    await screen.findByRole('alert')
    await user.click(screen.getByRole('button', { name: '重试' }))
    await screen.findByRole('img', { name: '净申赎估算' })
  })


  it.each(['1y', 'all'])('shows available totals and coverage for %s when a day is missing', async period => {
    const data = history()
    data.summary = { ...data.summary, days: 3, missing_net_dates: ['2026-11-11'], missing_amount_dates: ['2026-11-11'] }
    data.series.unshift({ ...data.series[0], date: '2026-11-11', net: null, amount: null, cumulative_net: null, cumulative_net_days: 0 })
    vi.mocked(etfApi.history).mockResolvedValue(data)
    render(<MemoryRouter initialEntries={[`/etf?period=${period}`]}><BroadEtf /></MemoryRouter>)
    await screen.findByRole('heading', { name: '已知净申赎累计' })
    const totals = document.querySelector('.etf-history-stats')!
    expect(totals.textContent).toContain('+2亿')
    expect(totals.textContent).toContain('+4亿')
    expect(totals.textContent).toContain('-2亿')
    expect(totals.textContent).toContain('20亿')
    expect(totals.querySelectorAll('.etf-card').length).toBe(4)
    expect(screen.getAllByText('已知数据合计 · 2/3交易日').length).toBeGreaterThanOrEqual(4)
    expect(etfApi.history).toHaveBeenCalledWith(expect.objectContaining({ period }), expect.any(AbortSignal))
  })

})
