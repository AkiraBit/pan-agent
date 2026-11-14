import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '@/i18n'
import ShortTermPage, { type Observation } from './ShortTerm'
import { fetchAPI } from '@panwatch/api/client'
vi.mock('@panwatch/api/client', () => ({ fetchAPI: vi.fn() }))
const request = vi.mocked(fetchAPI)
const q = { status: 'unavailable' as const, count: 0, expected: null }
const empty: Observation = { snapshot: null, phase: 'auction_late', server_time: '2026-11-11T01:22:00Z', collecting: false, retry_after: 0, error: null, history: [] }
const observation: Observation = { ...empty, phase: 'trading', snapshot: {
  id: 1, captured_at: '2026-11-11T01:00:00Z', trade_date: '2026-11-11', phase: 'trading', environment: 'broad_strength',
  market: { valid: 0, rising: 0, falling: 0, flat: 0, median: null, quality: q },
  concepts: q, themes: [], sentiment: { counts: { up: null, down: 0, broken: null, yesterday: null }, yesterday_mean: null, max_streak: null, break_rate: null, quality: { up: q } },
} }
beforeEach(async () => { await i18n.loadNamespaces('shortTerm'); request.mockReset() })
afterEach(cleanup)
describe('short-term observation entry', () => {
  it('explains the auction gap, then collects through the real client contract', async () => {
    request.mockResolvedValue(empty)
    render(<ShortTermPage />)
    await screen.findByText('动态竞价数据尚未接通')
    await screen.findByText(/重点比较同高度接力股/)
    fireEvent.click(screen.getByRole('button', { name: '采集一次' }))
    await waitFor(() => expect(request).toHaveBeenCalledWith('/short-term/refresh', { method: 'POST' }))
    expect(screen.queryByText('多股共同走强')).toBeNull()
  })
  it('marks stale observations and does not present missing breadth as zero', async () => {
    request.mockResolvedValue(observation)
    render(<ShortTermPage />)
    await screen.findByText('这份观察已过期，请重新采集后再判断当前市场。')
    expect(screen.queryByText('上涨范围较广')).toBeNull()
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(6)
    expect(screen.getByText('0')).toBeTruthy() // confirmed empty limit-down pool
  })
  it('shows transport failure and preserves the retry action', async () => {
    request.mockRejectedValue(new Error('offline'))
    render(<ShortTermPage />)
    await screen.findByRole('alert')
    request.mockResolvedValue(empty)
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
  })
  it('loads the English namespace without falling back to Chinese', async () => {
    await i18n.changeLanguage('en-US')
    request.mockResolvedValue(empty)
    render(<ShortTermPage />)
    await screen.findByText('Live auction data is not connected')
    expect(screen.getByRole('button', { name: 'Collect a snapshot' })).toBeTruthy()
  })
})
