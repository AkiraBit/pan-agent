import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { loadResearchView, loadResearchWorkspace, type ResearchManifest } from '@panwatch/api'
import '@/i18n'
import ResearchDataPage from './ResearchData'

vi.mock('@panwatch/api', async (original) => ({
  ...(await original<typeof import('@panwatch/api')>()),
  loadResearchWorkspace: vi.fn(),
  loadResearchView: vi.fn(),
}))
afterEach(() => { cleanup(); vi.clearAllMocks() })

const manifest: ResearchManifest = {
  sources: [{ enabled: true, available: true, priority: 1, provider: 'fuyao', name: '同花顺指数与板块成分' }],
  today: '2026-11-15', last_trade_date: '2026-11-13',
  views: [
    { id: 'directory', section: 'directory', title: '指数目录', description: '', fields: [], chart: null },
    { id: 'members', section: 'directory', title: '指数成分股', description: '',
      fields: [{ name: 'thscode', required: true, type: 'string', description: '完整指数代码' }], chart: null },
  ],
}
function mount(path = '/market-data/index_constituents') {
  return render(<MemoryRouter initialEntries={[path]}>
    <Routes><Route path="/market-data/:kind?" element={<ResearchDataPage />} /></Routes>
  </MemoryRouter>)
}

it('has a native entry for each workspace and drills from the index into its constituents', async () => {
  vi.mocked(loadResearchWorkspace).mockResolvedValue(manifest)
  vi.mocked(loadResearchView).mockImplementation(async (_kind, id) => ({
    provider: 'fuyao', source_name: '同花顺指数与板块成分',
    result: { item: id === 'directory' ? [{ thscode: '886042.TI', name: '白酒概念' }] : [{ thscode: '600519.SH', name: '贵州茅台' }] },
  }))
  mount()
  expect(await screen.findByText('白酒概念')).toBeTruthy()
  expect(screen.getByRole('link', { name: '期货研究' })).toBeTruthy()
  fireEvent.click(screen.getByRole('link', { name: '查看成分股' }))
  expect(await screen.findByText('贵州茅台')).toBeTruthy()
  expect(loadResearchView).toHaveBeenLastCalledWith('index_constituents', 'members', { thscode: '886042.TI' }, expect.any(AbortSignal), undefined)
  expect(screen.getByText('同花顺指数与板块成分')).toBeTruthy()
})

it('does not query a disabled source and links to the common source settings', async () => {
  vi.mocked(loadResearchWorkspace).mockResolvedValue({ ...manifest, sources: [{ ...manifest.sources[0], enabled: false }] })
  mount()
  expect(await screen.findByText('此业务还没有启用可用的数据源。')).toBeTruthy()
  expect(screen.getAllByRole('link', { name: '管理数据源与优先级' }).every(link => link.getAttribute('href') === '/datasources')).toBe(true)
  expect(loadResearchView).not.toHaveBeenCalled()
})

it('loads available indicators for the strategy editor before running a backtest', async () => {
  vi.mocked(loadResearchWorkspace).mockResolvedValue({ ...manifest, views: [
    { id: 'strategy', section: 'strategy', title: '条件回测', description: '', fields: [], chart: 'strategy' },
  ] })
  vi.mocked(loadResearchView).mockResolvedValue({ provider: 'fuyao', source_name: '同花顺基金回测', result: [
    { indicator_code: 'rsi_pct', indicator_name: '净值波动', support_operation: '>,<' },
  ] })
  mount('/market-data/fund_backtest')
  await waitFor(() => expect(loadResearchView).toHaveBeenCalledWith('fund_backtest', 'indicators', {}, expect.any(AbortSignal)))
  expect(screen.getByRole('group', { name: '买入条件' })).toBeTruthy()
  expect(screen.getByRole('group', { name: '卖出条件' })).toBeTruthy()
  expect(screen.getByRole('button', { name: '运行回测' }).hasAttribute('disabled')).toBe(true)
})
