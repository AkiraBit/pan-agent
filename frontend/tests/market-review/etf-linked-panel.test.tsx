import { fireEvent, render, screen, cleanup } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { EtfIntraday } from '@panwatch/api/etf'
import { LinkedEtfPanel } from '@/components/etf/LinkedEtfPanel'

vi.mock('@panwatch/api/etf', () => ({ etfApi: { analysis: vi.fn().mockResolvedValue({ groups: [], benchmarks: [], boards: {} }) } }))
vi.mock('@/components/etf/IntradayChart', () => ({ IntradayChart: () => <div /> }))
afterEach(cleanup)
const data = { date: '2026-11-17', symbols: ['510300.SH'], etf_count: 1, points: [
  { minute: '09:30', turnover_cny: 10e8, etf_count: 1 },
  { minute: '09:31', turnover_cny: 20e8, etf_count: 1 },
  { minute: '09:32', turnover_cny: 30e8, etf_count: 1 },
] } as EtfIntraday

describe('ETF interval editing', () => {
  it('commits a completed time edit on blur and rejects lunch minutes without changing statistics', async () => {
    render(<LinkedEtfPanel data={data} prices={[]} />)
    expect(await screen.findByText('09:30 – 09:32')).toBeTruthy()
    const end = screen.getByLabelText('结束时间')
    fireEvent.change(end, { target: { value: '09:31:00' } })
    expect(screen.getByText('09:30 – 09:32')).toBeTruthy()
    fireEvent.blur(end)
    expect(screen.getByText('09:30 – 09:31')).toBeTruthy()
    fireEvent.change(end, { target: { value: '12:00' } })
    fireEvent.blur(end)
    expect(screen.getByRole('alert').textContent).toContain('已结束的交易分钟')
    expect(screen.getByText('09:30 – 09:31')).toBeTruthy()
  })
})
