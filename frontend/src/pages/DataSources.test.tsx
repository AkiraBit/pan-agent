import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ConfirmProvider } from '@panwatch/base-ui/components/ui/confirm-dialog'
import { fetchAPI } from '@panwatch/api'
import '@/i18n'
import DataSourcesPage from './DataSources'

vi.mock('@panwatch/api', () => ({ fetchAPI: vi.fn(), resetDataSourcesToSeed: vi.fn() }))
const request = vi.mocked(fetchAPI)
const source = { id: 80, name: '腾讯 ETF 历史行情', type: 'etf_history', provider: 'tencent',
  config: {}, enabled: true, priority: 0, supports_batch: false, test_symbols: ['510300'], connection_status: 'ready' }
function fuyaoEntry(id: number, operation: string, name: string, business: string, suffix: string) {
  return { ...source, id, name, type: `fuyao:${operation}`, provider: 'fuyao', business_type: business,
    fuyao_operation: { id: operation, summary: name, method: 'GET', group: 'a-share',
      path: `/api/a-share/${suffix}`, description: name, docs_url: 'https://fuyao.aicubes.cn/',
      parameters: [{ name: 'thscode', type: 'string', description: '证券代码', required: true, example: '600519.SH' }] } }
}
beforeEach(() => { request.mockReset() })
afterEach(cleanup)

it('filters FTShare by plan and saves only the documented parameters from the settings panel', async () => {
  const operation = {
    id: 'get_stock_share', tier: 'basic', summary: '股本', group: '股票数据', subgroup: '财务数据', method: 'GET',
    docs_url: 'https://market.ft.tech/gateway/doc/p/rmoimhs7',
    variants: [{ path: '/api/v2/market/data/share/get-stock-share',
      parameters: [{ name: 'date', type: 'string', required: true, description: '日期 YYYYMMDD', format: 'YYYYMMDD' }],
      rules: [], preset: { date: '20260716' } }],
  }
  const sources = [
    { ...source, id: 300, provider: 'ftshare', type: 'ftshare:get_stock_share', name: '股本', ftshare_operation: operation },
    { ...source, id: 301, provider: 'ftshare', type: 'ftshare:factor', name: '股票复权因子',
      ftshare_operation: { ...operation, id: 'factor', tier: 'free', group: 'ETF专题' } },
    { ...source, id: 302, provider: 'ftshare', type: 'ftshare:snapshot', name: '盘前行情',
      ftshare_operation: { ...operation, id: 'snapshot', subgroup: '行情数据' } },
  ]
  request.mockImplementation(async path => {
    if (path === '/datasources/providers') return { paused: [] }
    if (path === '/settings/data-providers/ftshare') return { configured: true }
    return sources
  })
  render(<DataSourcesPage />)
  fireEvent.click(await screen.findByRole('button', { name: 'FTShare' }))
  expect(screen.getByRole('link', { name: 'API调试' }).getAttribute('href')).toBe('/datasources/ftshare')
  expect(screen.getByRole('row', { name: /股票复权因子.*免费版/ })).toBeTruthy()
  const categories = screen.getByRole('group', { name: '接口分类' })
  fireEvent.click(within(categories).getByRole('button', { name: 'ETF专题' }))
  expect(screen.queryByText('股本')).toBeNull()
  const filter = screen.getByRole('group', { name: '按套餐筛选' })
  fireEvent.click(within(filter).getByRole('button', { name: '基础版' }))
  expect(screen.queryByText('股票复权因子')).toBeNull()
  expect(screen.getByText('没有匹配的接口。')).toBeTruthy()
  fireEvent.click(within(categories).getByRole('button', { name: '股票数据' }))
  const subcategories = screen.getByRole('group', { name: '接口子分类' })
  expect(within(subcategories).getAllByRole('button').map(button => button.textContent)).toEqual(['全部', '行情数据', '财务数据'])
  fireEvent.click(within(subcategories).getByRole('button', { name: '财务数据' }))
  expect(screen.queryByText('盘前行情')).toBeNull()
  fireEvent.change(screen.getByRole('searchbox', { name: '搜索当前来源' }), { target: { value: 'get stock share' } })
  expect(screen.getByRole('row', { name: /股本.*基础版/ })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '设置股本' }))
  const dialog = screen.getByRole('dialog')
  expect(within(dialog).getByText('基础版')).toBeTruthy()
  const date = within(dialog).getByRole('textbox', { name: 'date' }) as HTMLInputElement
  expect(date.value).toBe('20260716')
  expect(within(dialog).getAllByRole('textbox')).toHaveLength(1)
  fireEvent.change(date, { target: { value: '20261012' } })
  fireEvent.click(within(dialog).getByRole('button', { name: '保存' }))
  await waitFor(() => expect(request).toHaveBeenCalledWith('/datasources/300', {
    method: 'PUT', body: '{"config":{"variant":0,"params":{"date":"20261012"}}}',
  }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
})

it('searches the selected provider locally and locates a result from another provider globally', async () => {
  request.mockImplementation(async path => path === '/datasources/providers' ? { paused: [] } : [
    source,
    { ...source, id: 81, provider: 'fuyao', name: '同花顺指数日 K 线', type: 'index_kline' },
    { ...source, id: 82, provider: 'fuyao', name: '同花顺标的检索', type: 'stock_search' },
  ])
  render(<DataSourcesPage />)
  await screen.findByRole('row', { name: /同花顺标的检索/ })
  const scopedSearch = screen.getByRole('searchbox', { name: '搜索当前来源' })
  fireEvent.change(scopedSearch, { target: { value: 'K线' } })
  expect(screen.queryByRole('row', { name: /同花顺标的检索/ })).toBeNull()
  expect(screen.getByRole('row', { name: /同花顺指数日 K 线/ })).toBeTruthy()
  fireEvent.change(scopedSearch, { target: { value: 'ETF 历史行情' } })
  expect(screen.getByText('没有匹配的接口。')).toBeTruthy()

  fireEvent.click(screen.getByRole('button', { name: '搜索全部接口' }))
  const dialog = screen.getByRole('dialog', { name: '搜索全部接口' })
  fireEvent.change(within(dialog).getByRole('searchbox'), { target: { value: '腾讯 ETF 历史行情' } })
  fireEvent.click(within(dialog).getByRole('button', { name: /腾讯 ETF 历史行情/ }))
  const row = await screen.findByRole('row', { name: /腾讯 ETF 历史行情/ })
  await waitFor(() => expect(document.activeElement).toBe(row))
  expect(screen.getByRole('button', { name: '腾讯财经' }).getAttribute('aria-pressed')).toBe('true')
  expect(screen.queryByRole('searchbox', { name: '搜索当前来源' })).toBeNull()
})

it('links Fuyao to the shared key configuration and gates its switch', async () => {
  request.mockResolvedValue([{ ...source, name: '同花顺 A 股行情', type: 'quote', provider: 'fuyao',
    enabled: false, connection_status: 'authorization_required' }])
  render(<ConfirmProvider labels={{ title: '确认', confirm: '确定', cancel: '取消' }}><DataSourcesPage /></ConfirmProvider>)
  const link = await screen.findByRole('link', { name: '管理同花顺 API Key' })
  expect(link.getAttribute('href')).toBe('/settings#sec-data-providers')
  expect(screen.getByRole('link', { name: 'API调试' }).getAttribute('href')).toBe('/datasources/fuyao')
  expect(screen.getByRole('switch', { name: '启用同花顺 A 股行情' }).hasAttribute('disabled')).toBe(true)
  expect(screen.getByTitle('测试连接').hasAttribute('disabled')).toBe(true)
})

it('keeps FTShare in the provider list without registering any endpoints', async () => {
  request.mockImplementation(async path => path === '/settings/data-providers/ftshare'
    ? { configured: true } : [source])
  render(<DataSourcesPage />)
  fireEvent.click(await screen.findByRole('button', { name: /FTShare/ }))
  expect(await screen.findByText('API Key 已配置')).toBeTruthy()
  expect(screen.getByText('暂无数据源')).toBeTruthy()
  expect(screen.getByRole('link', { name: '管理 API Key' }).getAttribute('href')).toBe('/settings#sec-data-providers')
  expect(within(screen.getByRole('navigation', { name: '数据来源' })).getAllByRole('switch')).toHaveLength(6)
})

it('pauses an entire provider without changing the preferences of its individual endpoints', async () => {
  const sources = [
    fuyaoEntry(10, 'get_a_share_prices_snapshot', '同花顺实时行情', 'quote', 'prices/snapshot'),
    { ...source, id: 11, name: '同花顺北向资金', type: 'northbound', provider: 'ths', provider_group: 'fuyao', enabled: false },
    { ...source, id: 12, name: '腾讯实时行情', type: 'quote', provider: 'tencent' },
    { ...fuyaoEntry(13, 'get_a_share_financials_income_statements', '利润表', 'fundamentals', 'financials/income-statements'), enabled: false },
  ]
  let paused = false
  request.mockImplementation(async (path, options) => {
    if (path === '/datasources/providers/fuyao' && options?.body) {
      paused = !JSON.parse(String(options.body)).enabled
      return { provider: 'fuyao', enabled: !paused }
    }
    if (path === '/datasources/providers') return { paused: paused ? ['fuyao'] : [] }
    return sources
  })
  const app = render(<DataSourcesPage />)
  expect(await screen.findByText('2 个接口 · 1 个已启用')).toBeTruthy()
  fireEvent.click(await screen.findByRole('switch', { name: '启用同花顺来源' }))
  await waitFor(() => expect(screen.getByRole('switch', { name: '启用同花顺来源' }).getAttribute('aria-checked')).toBe('false'))
  expect(screen.getByText('2 个接口 · 0 个已启用')).toBeTruthy()
  expect(request).toHaveBeenCalledWith('/datasources/providers/fuyao', { method: 'PUT', body: '{"enabled":false}' })
  expect(screen.getByRole('button', { name: '测试同花顺实时行情' }).hasAttribute('disabled')).toBe(true)
  const providers = within(screen.getByRole('navigation', { name: '数据来源' }))
  fireEvent.click(providers.getByRole('button', { name: /腾讯财经/ }))
  expect(screen.getByRole('switch', { name: '启用腾讯实时行情' }).hasAttribute('disabled')).toBe(false)
  app.unmount()
  render(<DataSourcesPage />)
  const master = await screen.findByRole('switch', { name: '启用同花顺来源' })
  expect(master.getAttribute('aria-checked')).toBe('false')
  fireEvent.click(master)
  await waitFor(() => expect(master.getAttribute('aria-checked')).toBe('true'))
  expect(screen.getByText('2 个接口 · 1 个已启用')).toBeTruthy()
  expect(screen.getByRole('switch', { name: '启用同花顺实时行情' }).getAttribute('aria-checked')).toBe('true')
  expect(screen.getByRole('switch', { name: '启用同花顺北向资金' }).getAttribute('aria-checked')).toBe('false')
  expect(request.mock.calls.filter(([, options]) => options?.method === 'PUT').map(([path]) => path))
    .toEqual(['/datasources/providers/fuyao', '/datasources/providers/fuyao'])
})

it('configures, tests and pauses a single Fuyao endpoint without changing its sibling', async () => {
  const income = fuyaoEntry(24, 'get_a_share_financials_income_statements', '利润表', 'fundamentals', 'financials/income-statements')
  const balance = fuyaoEntry(25, 'get_a_share_financials_balance_sheets', '资产负债表', 'fundamentals', 'financials/balance-sheets')
  request.mockImplementation(async path => {
    if (path === '/datasources/providers') return { paused: [] }
    if (path === '/datasources/24/test') return { source_name: income.name, source_type: income.type,
      provider: 'fuyao', test_passed: true, http_status: 200, business_code: 0, raw_response: '{"code":0,"data":[]}' }
    return [income, balance]
  })
  render(<DataSourcesPage />)
  await screen.findByText('2 个接口 · 2 个已启用')
  expect(within(screen.getByRole('group', { name: '接口分类' })).getAllByRole('button')).toHaveLength(2)
  const search = screen.getByRole('searchbox', { name: '搜索当前来源' })
  fireEvent.change(search, { target: { value: 'income-statements' } })
  expect(screen.queryByRole('row', { name: /资产负债表/ })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '清除搜索' }))
  expect(document.activeElement).toBe(search)
  expect(screen.getByRole('row', { name: /资产负债表/ })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '设置利润表' }))
  const dialog = screen.getByRole('dialog')
  const field = within(dialog).getByRole('textbox', { name: /thscode/ })
  expect(field).toHaveProperty('value', '600519.SH')
  fireEvent.change(field, { target: { value: '000001.SZ' } })
  fireEvent.click(within(dialog).getByRole('button', { name: '保存' }))
  await waitFor(() => expect(request).toHaveBeenCalledWith('/datasources/24', {
    method: 'PUT', body: '{"config":{"params":{"thscode":"000001.SZ"}}}',
  }))
  fireEvent.click(await screen.findByRole('button', { name: '测试利润表' }))
  expect(await screen.findByText('{"code":0,"data":[]}')).toBeTruthy()
  expect(request).toHaveBeenCalledWith('/datasources/24/test', { method: 'POST', timeoutMs: 30_000 })
  fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
  fireEvent.click(await screen.findByRole('switch', { name: '启用利润表' }))
  await screen.findByText('2 个接口 · 1 个已启用')
  expect(screen.getByRole('switch', { name: '启用资产负债表' }).getAttribute('aria-checked')).toBe('true')
  expect(screen.getByRole('button', { name: '测试利润表' }).hasAttribute('disabled')).toBe(true)
})

it('switches all REST endpoints of the active provider even when filtered', async () => {
  const income = fuyaoEntry(24, 'get_a_share_financials_income_statements', '利润表', 'fundamentals', 'financials/income-statements')
  const balance = { ...fuyaoEntry(25, 'get_a_share_financials_balance_sheets', '资产负债表', 'fundamentals', 'financials/balance-sheets'), enabled: false }
  request.mockImplementation(async (path, options) => {
    if (path === '/datasources/providers') return { paused: [] }
    if (path === '/datasources/providers/fuyao/endpoints') return { ...JSON.parse(String(options?.body)), source_ids: [24, 25] }
    return [income, balance, source]
  })
  render(<DataSourcesPage />)
  await screen.findByText('2 个接口 · 1 个已启用')
  fireEvent.change(screen.getByRole('searchbox', { name: '搜索当前来源' }), { target: { value: '利润表' } })
  expect(screen.queryByRole('row', { name: /资产负债表/ })).toBeNull()
  const bulkMenu = screen.getByRole('button', { name: '当前来源的全部接口开关' })
  expect(screen.queryByRole('button', { name: '全部关闭' })).toBeNull()
  fireEvent.click(bulkMenu)
  fireEvent.click(screen.getByRole('button', { name: '全部关闭' }))
  await screen.findByText('2 个接口 · 0 个已启用')
  expect(bulkMenu.getAttribute('aria-expanded')).toBe('false')
  fireEvent.click(bulkMenu)
  expect(screen.getByRole('button', { name: '全部关闭' }).hasAttribute('disabled')).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: '全部开启' }))
  await screen.findByText('2 个接口 · 2 个已启用')
  expect(screen.getByRole('switch', { name: '启用同花顺来源' }).getAttribute('aria-checked')).toBe('true')
  expect(request.mock.calls.filter(([, options]) => options?.method === 'PUT').map(([path, options]) => [path, options?.body]))
    .toEqual([['/datasources/providers/fuyao/endpoints', '{"enabled":false}'], ['/datasources/providers/fuyao/endpoints', '{"enabled":true}']])
})

it('shows FTShare then iFinD for matching contracts and separates independent vendors', async () => {
  const routing = { key: 'quote', category: 'quote_kline', label: '实时行情', markets: ['CN'] }
  const rows = [
    { ...source, id: 100, name: '腾讯行情', type: 'quote', provider: 'tencent', priority: -10,
      routing: { ...routing, mode: 'direct' } },
    { ...source, id: 101, name: '同花顺 A 股行情', type: 'quote', provider: 'fuyao', priority: 0,
      routing: { ...routing, mode: 'fallback' } },
    { ...source, id: 102, name: 'FTShare A 股行情', type: 'ftshare:stock_daec_stocks', provider: 'ftshare', priority: 50,
      connection_status: 'authorization_required', routing: { ...routing, mode: 'fallback' } },
  ]
  request.mockResolvedValue(rows)
  render(<ConfirmProvider labels={{ title: '确认', confirm: '确定', cancel: '取消' }}><DataSourcesPage /></ConfirmProvider>)
  await screen.findByText('同花顺 A 股行情')
  fireEvent.click(screen.getByRole('button', { name: '调用顺序' }))
  const order = within(await screen.findByRole('dialog', { name: '调用顺序' }))
  expect(order.getByRole('combobox').textContent).toContain('实时行情')
  const [first, second] = order.getAllByRole('listitem')
  expect(within(first).getByText('FTShare A 股行情')).toBeTruthy()
  expect(within(first).getByText('主源')).toBeTruthy()
  expect(within(first).getByText('待授权')).toBeTruthy()
  expect(within(second).getByText('同花顺 A 股行情')).toBeTruthy()
  expect(within(second).getByText('备源')).toBeTruthy()
  expect(order.queryByText('腾讯行情')).toBeNull()
  expect(order.queryByRole('button', { name: /上移|下移|设为主源/ })).toBeNull()

  fireEvent.change(order.getByRole('searchbox', { name: '搜索数据类型、接口或来源' }), { target: { value: '腾讯' } })
  expect(order.getByText('独立调用')).toBeTruthy()
  expect(order.getByText('腾讯行情')).toBeTruthy()
  expect(order.queryByText('主源')).toBeNull()
})

it('configures the actual params for a market-wide test without asking for symbols', async () => {
  request.mockImplementation(async path => path === '/datasources/providers' ? { paused: [] } : [{
    ...source, id: 90, name: '财联社电报', type: 'flash_news', provider: 'cls',
    test_settings: { symbols: null, test_symbols: [], values: {},
      fields: [{ key: 'limit', type: 'integer', default: 20, wire: 'rn', minimum: 1, maximum: 50 }] },
  }])
  render(<DataSourcesPage />)
  fireEvent.click(await screen.findByRole('button', { name: '设置财联社电报' }))
  const dialog = screen.getByRole('dialog')
  expect(within(dialog).queryByRole('textbox')).toBeNull()
  const limit = within(dialog).getByRole('spinbutton', { name: /快讯条数/ }) as HTMLInputElement
  expect(limit.value).toBe('20')
  expect(limit.max).toBe('50')
  expect(within(dialog).getByText('rn')).toBeTruthy()
  fireEvent.change(limit, { target: { value: '8' } })
  fireEvent.click(within(dialog).getByRole('button', { name: '保存' }))
  await waitFor(() => expect(request).toHaveBeenCalledWith('/datasources/90', {
    method: 'PUT', body: '{"test_params":{"limit":"8"}}',
  }))
})

it('tests the selected provider when two endpoints have the same name and type', async () => {
  const quotes = [
    { ...source, id: 80, name: '实时行情', type: 'quote', provider: 'fuyao' },
    { ...source, id: 81, name: '实时行情', type: 'quote', provider: 'tencent' },
  ]
  request.mockImplementation(async (path) => path.endsWith('/test')
    ? { test_passed: true, source_name: '实时行情', source_type: 'quote', provider: 'tencent',
        count: 1, duration_ms: 5, items: [], test_symbols: ['510300'], logs: [] }
    : quotes)
  render(<ConfirmProvider labels={{ title: "确认", confirm: "确定", cancel: "取消" }}><DataSourcesPage /></ConfirmProvider>)
  expect(await screen.findAllByRole('switch', { name: '启用实时行情' })).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', { name: /腾讯财经/ }))
  fireEvent.click(screen.getByRole('button', { name: '测试实时行情' }))
  await screen.findByRole('dialog', { name: /测试结果/ })
  expect(request).toHaveBeenCalledWith('/datasources/81/test', { method: 'POST' })
  expect(request).not.toHaveBeenCalledWith('/datasources/80/test', expect.anything())
})

it('shows exactly six flat providers, each with a local logo and a directly actionable switch', async () => {
  const writes: string[] = []
  request.mockImplementation(async (path, options) => {
    if (options?.method === 'PUT') writes.push(path)
    if (path === '/datasources/providers') return { paused: [] }
    return [{ ...source, name: '雪球资讯', provider: 'xueqiu' },
      { ...source, id: 81, name: '长桥行情', provider: 'longbridge' }, source]
  })
  render(<DataSourcesPage />)
  const navigation = within(await screen.findByRole('navigation', { name: '数据来源' }))
  expect(navigation.getAllByRole('button').map(button => button.textContent))
    .toEqual(['同花顺', 'FTShare', '财联社', '东方财富', '腾讯财经', '新浪财经'])
  expect(navigation.queryByText('其他来源')).toBeNull()
  expect(navigation.queryByText('雪球')).toBeNull()
  expect(navigation.getAllByRole('button').map(button => button.querySelector('img')?.getAttribute('src')))
    .toEqual(['fuyao', 'ftshare', 'cls', 'eastmoney', 'tencent', 'sina'].map(id => '/providers/' + id + '.png'))
  fireEvent.click(navigation.getByRole('switch', { name: '启用东方财富来源' }))
  await waitFor(() => expect(writes).toEqual(['/datasources/providers/eastmoney']))
  expect(screen.getByRole('heading', { name: '腾讯财经' })).toBeTruthy()
  expect(screen.queryByText('长桥行情')).toBeNull()
})
