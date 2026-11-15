import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { emotionApi, type SentimentOverview, type SentimentSupplement } from '@panwatch/api/emotion'
import i18n from '@/i18n'
import SentimentReportDetails, { SentimentReportExport } from './SentimentReportDetails'
import SentimentStructure from './SentimentStructure'

vi.mock('@panwatch/api/emotion', () => ({ emotionApi: { downloadOverview: vi.fn(), previewOverview: vi.fn() } }))
beforeEach(async () => { vi.clearAllMocks(); await i18n.changeLanguage('zh-CN'); await i18n.loadNamespaces('emotion') })
afterEach(cleanup)

it('previews the exact exported document in a sandboxed dialog', async () => {
  vi.mocked(emotionApi.previewOverview).mockResolvedValue('<html><body>Report snapshot<a href="#evidence">Source</a><details id="evidence">Source content</details></body></html>')
  render(<SentimentReportExport runId="preview-run" />)
  fireEvent.click(screen.getByRole('button', { name: '预览结果页' }))
  const frame = await screen.findByTitle('预览结果页')
  expect(frame.getAttribute('sandbox')).toBe('')
  expect(frame.getAttribute('srcdoc')).toContain('Report snapshot')
  expect(frame.getAttribute('srcdoc')).toContain('href="about:srcdoc#evidence"')
  expect(emotionApi.previewOverview).toHaveBeenCalledWith('preview-run')
})

it('exports the displayed run and reports a failed download without claiming success', async () => {
  vi.mocked(emotionApi.downloadOverview).mockRejectedValueOnce(new Error('offline'))
  render(<SentimentReportExport runId="frozen-run" />)
  fireEvent.click(screen.getByRole('button', { name: '导出结果页' }))
  await screen.findByRole('alert')
  expect(emotionApi.downloadOverview).toHaveBeenCalledWith('frozen-run', 'html')
  vi.mocked(emotionApi.downloadOverview).mockResolvedValueOnce()
  fireEvent.click(screen.getByRole('button', { name: '导出源数据 JSON' }))
  await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
  expect(emotionApi.downloadOverview).toHaveBeenLastCalledWith('frozen-run', 'json')
})

it('renders missing history without fabricating successful forecasts', async () => {
  const overview = { report: { continuity: { source_run_id: null, checks: [] }, revision: null, data_gaps: [] } } as unknown as SentimentOverview
  render(<SentimentReportDetails overview={overview} />)
  expect(screen.getByText(/首次运行不补造历史命中/)).toBeTruthy()
  expect(screen.queryByText('观察条件成立')).toBeNull()
  await act(async () => { await i18n.changeLanguage('en-US') })
  await screen.findByText(/No registered checks/)
})

it('separates incomplete ladders, empty complete pools and single-day disclosure records', () => {
  const data: SentimentSupplement = {
    trade_date: '2026-11-13', collected_at: '2026-11-15T00:00:00Z',
    statistics: { status: 'missing', data: null },
    pools: { up: { status: 'partial', total: null, rows: [] }, down: { status: 'missing', total: null, rows: [] }, broken: { status: 'missing', total: null, rows: [] } },
    ladders: [{ board: 'main', status: 'partial', sample: 0, excluded_or_unknown: 0, levels: [], highest: null, first_board_ratio: null },
      { board: 'star', status: 'available', sample: 0, excluded_or_unknown: 0, levels: [], highest: null, first_board_ratio: null }],
    dragon_tiger: { status: 'available', data: { stock_items: [{ thscode: '600000.SH', name: '单日记录', range_days: 1, net_value: 100 }, { thscode: '600000.SH', name: '三日记录', range_days: 3, net_value: 300 }] } },
  }
  render(<SentimentStructure data={data} />)
  expect(screen.getByText(/事件池或板数字段不完整/)).toBeTruthy()
  expect(screen.getByText(/完整返回池中无符合/)).toBeTruthy()
  expect(screen.getByText(/单日记录 · 600000.SH/)).toBeTruthy()
  expect(screen.queryByText(/三日记录 · 600000.SH/)).toBeNull()
})
