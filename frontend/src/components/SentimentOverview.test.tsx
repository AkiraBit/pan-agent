import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { emotionApi, type SentimentOverviewState } from '@panwatch/api/emotion'
import i18n from '@/i18n'
import SentimentOverview from './SentimentOverview'
import SentimentCycleChart from './SentimentCycleChart'

vi.mock('@panwatch/api/emotion', () => ({ emotionApi: { overview: vi.fn(), refreshOverview: vi.fn() } }))
const state: SentimentOverviewState = { overview: null, stale: true, active_run: null, last_run: null, can_analyze: true, skill_enabled: true, connection_status: 'ready', retry_after: null, server_time: '2026-11-15T00:00:00Z' }
beforeEach(async () => { vi.clearAllMocks(); await i18n.changeLanguage('zh-CN'); await i18n.loadNamespaces('emotion') })
afterEach(cleanup)
it('automatically requests the latest session without a date or revision and deduplicates while active', async () => {
  vi.mocked(emotionApi.overview).mockResolvedValueOnce(state).mockResolvedValue({ ...state, active_run: { id: 'r1', status: 'running' } as NonNullable<SentimentOverviewState['active_run']> })
  vi.mocked(emotionApi.refreshOverview).mockResolvedValue({ run: null, started: true })
  render(<MemoryRouter><SentimentOverview inputVersion={0} onEvidence={() => {}} /></MemoryRouter>)
  await waitFor(() => expect(emotionApi.refreshOverview).toHaveBeenCalledTimes(1))
  expect(emotionApi.refreshOverview).toHaveBeenCalledWith({ request_key: expect.any(String), language: 'zh-CN', force: false })
  expect(screen.queryByLabelText('分析版本')).toBeNull()
  expect(screen.queryByLabelText('生成目标交易日')).toBeNull()
  await screen.findByText(/正在读取长桥市场数据/)
})
it('honors a disabled skill and a failed-run cooldown without silently triggering retries', async () => {
  vi.mocked(emotionApi.overview).mockResolvedValue({ ...state, can_analyze: false, skill_enabled: false })
  const view = render(<MemoryRouter><SentimentOverview inputVersion={0} onEvidence={() => {}} /></MemoryRouter>)
  expect(await screen.findByRole('link', { name: '打开 MCP & 技能' })).toBeTruthy()
  expect(emotionApi.refreshOverview).not.toHaveBeenCalled()
  view.unmount()
  vi.mocked(emotionApi.overview).mockResolvedValue({ ...state, retry_after: '2026-11-15T00:10:00Z' })
  render(<MemoryRouter><SentimentOverview inputVersion={0} onEvidence={() => {}} /></MemoryRouter>)
  await screen.findByRole('button', { name: '更新市场判断' })
  await waitFor(() => expect(emotionApi.overview).toHaveBeenCalledTimes(2))
  expect(emotionApi.refreshOverview).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '更新市场判断' }))
  await waitFor(() => expect(emotionApi.refreshOverview).toHaveBeenCalledWith(expect.objectContaining({ force: true })))
})
it('renders adjacent intervals and the wrap into ice without inventing progress percentages', async () => {
  const view = render(<SentimentCycleChart position={{ kind: 'between', stages: ['repair','expansion'], status: 'candidate', rationale: '两类证据尚不能明确区分。', evidence_ids: ['a'] }} />)
  expect(screen.getByRole('img').getAttribute('aria-label')).toContain('修复与发酵/扩张之间')
  expect(screen.queryByText('50%')).toBeNull()
  view.rerender(<SentimentCycleChart position={{ kind: 'between', stages: ['retreat','ice'], status: 'conflicted', rationale: '尚未确认冰点。', evidence_ids: ['b'] }} />)
  expect(screen.getByRole('img').getAttribute('aria-label')).toContain('退潮与低迷/冰点之间')
  view.rerender(<SentimentCycleChart position={{ kind: 'unknown', stages: [], status: 'insufficient', rationale: '无法定位。', evidence_ids: [] }} />)
  expect(screen.getByRole('img').getAttribute('aria-label')).toContain('证据不足，暂不定位')
  await i18n.changeLanguage('en-US')
  await waitFor(() => expect(screen.getByRole('img').getAttribute('aria-label')).toContain('Insufficient evidence'))
})
it('shows the exact missing data and waits for an explicit refresh', async () => {
  vi.mocked(emotionApi.overview).mockResolvedValue({ ...state, last_run: {
    id: 'missing-data', status: 'failed', error_code: 'overview_report_data_missing',
    target_trade_date: '2026-11-13', created_at: state.server_time, finished_at: state.server_time,
    base_revision: 0, model_label: null, publication_id: null,
    events: [{ seq: 1, type: 'data_required', at: state.server_time, data: { missing: ['上一交易日涨跌停池与晋级统计'] } }],
  } as NonNullable<SentimentOverviewState['last_run']> })
  vi.mocked(emotionApi.refreshOverview).mockResolvedValue({ run: null, started: true })
  render(<MemoryRouter><SentimentOverview inputVersion={0} onEvidence={() => {}} /></MemoryRouter>)
  expect(await screen.findByText('上一交易日涨跌停池与晋级统计')).toBeTruthy()
  expect(emotionApi.refreshOverview).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '更新市场判断' }))
  await waitFor(() => expect(emotionApi.refreshOverview).toHaveBeenCalledWith(expect.objectContaining({ force: true })))
})
