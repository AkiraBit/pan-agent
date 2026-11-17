import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { getFtshareCatalog, queryFtshare, type FtshareCatalog } from '@panwatch/api'
import '@/i18n'
import FtshareRestPage from './FtshareRest'

vi.mock('@panwatch/api', () => ({ getFtshareCatalog: vi.fn(), queryFtshare: vi.fn() }))
afterEach(cleanup)

it('shows plan labels and submits a prefilled official HTTP example', async () => {
  const base = { method: 'GET', docs_url: 'https://market.ft.tech/gateway/doc/p/demo', group: '股票数据', enabled: true, settings: null } as const
  const catalog: FtshareCatalog = { configured: true, paused: false, source: base.docs_url, operations: [
    { ...base, id: 'free_factor', summary: 'ETF复权因子', tier: 'free', group: 'ETF专题', variants: [{ path: '/api/v1/factor', rules: [], parameters: [], preset: {} }] },
    { ...base, id: 'basic_share', summary: '股本', tier: 'basic', variants: [{ path: '/api/v2/market/data/share/get-stock-share',
      rules: [], parameters: [{ name: 'date', type: 'string', required: true, format: 'YYYYMMDD', description: '日期 YYYYMMDD' }],
      preset: { date: '20260716' } }] },
  ] }
  vi.mocked(getFtshareCatalog).mockResolvedValue(catalog)
  vi.mocked(queryFtshare).mockResolvedValue({ http_status: 200, business_code: 200, message: 'success',
    response_json: '{"code":200,"data":[9223372036854775807]}' })
  render(<MemoryRouter initialEntries={['/datasources/ftshare?operation=basic_share']}><FtshareRestPage /></MemoryRouter>)
  const side = await screen.findByRole('complementary')
  expect(within(side).getByRole('button', { name: /ETF复权因子.*免费版/ })).toBeTruthy()
  expect(within(side).getByRole('button', { name: /股本.*基础版/ })).toBeTruthy()
  const categories = screen.getByRole('group', { name: '接口分类' })
  fireEvent.click(within(categories).getByRole('button', { name: '股票数据' }))
  expect(within(side).queryByRole('button', { name: /ETF复权因子/ })).toBeNull()
  expect((screen.getByRole('textbox', { name: 'date' }) as HTMLInputElement).value).toBe('20260716')
  fireEvent.click(screen.getByRole('button', { name: '发送查询' }))
  expect(await screen.findByText(/9223372036854775807/)).toBeTruthy()
  expect(queryFtshare).toHaveBeenCalledWith('basic_share', { variant: 0, params: { date: '20260716' } }, expect.any(AbortSignal))
})
