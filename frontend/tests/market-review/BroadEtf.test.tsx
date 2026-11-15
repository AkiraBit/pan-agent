import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import BroadEtf from '@/pages/BroadEtf'
import { etfApi, type EtfBoard, type EtfNationalTeam } from '@panwatch/api/etf'
import i18n from '@/i18n'

vi.mock('@panwatch/api/etf', () => ({ etfApi: { board: vi.fn(), dates: vi.fn(), national: vi.fn() } }))

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

beforeEach(async () => {
  await i18n.loadNamespaces('etf')
  vi.clearAllMocks()
  vi.mocked(etfApi.board).mockImplementation(async date => ({ payload: board(date || undefined), stale: false, snapshot_id: 1, observed_at: '' }))
  vi.mocked(etfApi.dates).mockResolvedValue(['2026-11-13', '2026-11-12'])
  vi.mocked(etfApi.national).mockResolvedValue(national)
})

describe('broad-market ETF dashboard', () => {
  it('opens the overview, expands market data, and navigates trading dates', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter initialEntries={['/etf']}><BroadEtf /></MemoryRouter>)
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
    await screen.findByText('中央汇金投资有限责任公司')
    expect(screen.getByText('2025-12-31')).toBeTruthy()
    expect(screen.getByText('持仓ETF净申赎估算')).toBeTruthy()
    expect(screen.queryByText('国家队今日买入')).toBeNull()
    expect(screen.getByText('暂无逆势申购信号')).toBeTruthy()
  })

  it('offers retry when market data fails without inventing values', async () => {
    vi.mocked(etfApi.board).mockRejectedValueOnce(new Error('offline'))
    const user = userEvent.setup()
    render(<MemoryRouter><BroadEtf /></MemoryRouter>)
    await screen.findByRole('alert')
    await user.click(screen.getByRole('button', { name: '重试' }))
    await screen.findByRole('img', { name: '分钟成交' })
  })

  it('supports keyboard inspection of minute data', async () => {
    render(<MemoryRouter><BroadEtf /></MemoryRouter>)
    const chart = await screen.findByRole('img', { name: '分钟成交' })
    fireEvent.keyDown(chart, { key: 'ArrowLeft' })
    expect(screen.getByText('09:31')).toBeTruthy()
  })
})
