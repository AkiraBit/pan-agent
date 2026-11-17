import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { getFuyaoCatalog, queryFuyao, type FuyaoCatalog } from '@panwatch/api'
import '@/i18n'
import FuyaoRestPage from './FuyaoRest'

vi.mock('@panwatch/api', () => ({ getFuyaoCatalog: vi.fn(), queryFuyao: vi.fn() }))
afterEach(() => { cleanup(); vi.resetAllMocks() })

const catalog: FuyaoCatalog = {
  configured: true, paused: false, source: 'https://fuyao.aicubes.cn/openapi/financial-api.openapi.json', version: '1.0.0',
  operations: [
    { id: 'get_a_share_prices_snapshot', method: 'GET', path: '/api/a-share/prices/snapshot', group: 'a-share', enabled: true,
      summary: '行情快照', description: '最新行情', docs_url: 'https://fuyao.aicubes.cn/docs/api-reference/prices/',
      parameters: [{ name: 'thscodes', type: 'string', description: '股票代码', required: false }] },
    { id: 'get_meta_tickers_search', method: 'GET', path: '/api/meta/tickers/search', group: 'meta', enabled: true,
      summary: '标的检索', description: '搜索标的', docs_url: 'https://fuyao.aicubes.cn/docs/api-reference/ticker-search/',
      parameters: [{ name: 'q', type: 'string', description: '标的名称', required: true, example: '贵州茅台' }] },
  ],
}

function mount() {
  return render(<MemoryRouter><FuyaoRestPage /></MemoryRouter>)
}

it('finds an endpoint, requires its input, and displays the provider result as text', async () => {
  vi.mocked(getFuyaoCatalog).mockResolvedValue(catalog)
  vi.mocked(queryFuyao).mockResolvedValue({ http_status: 200, business_code: 2003, request_id: 'sample',
    response_json: '{"code":2003,"data":"<img src=x>","id":9223372036854775807}' })
  mount()
  await screen.findByRole('heading', { name: '行情快照' })
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: '/api/meta' } })
  expect(screen.queryByRole('button', { name: /行情快照/ })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: /标的检索/ }))
  expect(screen.getByRole('button', { name: '发送查询' }).hasAttribute('disabled')).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: '填入示例' }))
  fireEvent.click(screen.getByRole('button', { name: '发送查询' }))
  await screen.findByText('业务码 2003')
  expect(queryFuyao).toHaveBeenCalledWith('get_meta_tickers_search', { q: '贵州茅台' }, expect.any(AbortSignal))
  expect(screen.getByText(/9223372036854775807/).tagName).toBe('PRE')
  expect(document.querySelector('img')).toBeNull()
  expect(screen.getByRole('button', { name: '下载 JSON' })).toBeTruthy()
})

it('allows browsing all endpoint metadata without a configured key', async () => {
  vi.mocked(getFuyaoCatalog).mockResolvedValue({ ...catalog, configured: false })
  mount()
  await screen.findByText('请先配置 API Key。接口目录仍可浏览。')
  expect(screen.getByRole('button', { name: '发送查询' }).hasAttribute('disabled')).toBe(true)
  expect(screen.getByRole('link', { name: '管理同花顺 API Key' }).getAttribute('href')).toBe('/settings#sec-data-providers')
})

it('keeps operation metadata visible when the source is paused and disables sending', async () => {
  vi.mocked(getFuyaoCatalog).mockResolvedValue({ ...catalog, paused: true })
  mount()
  await screen.findByRole('heading', { name: '行情快照' })
  expect(screen.getByRole('button', { name: '发送查询' }).hasAttribute('disabled')).toBe(true)
  expect(screen.getByRole('link', { name: '前往数据源开启同花顺' }).getAttribute('href')).toBe('/datasources')
  expect(queryFuyao).not.toHaveBeenCalled()
})
