import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ConfirmProvider } from '@panwatch/base-ui/components/ui/confirm-dialog'
import { fetchAPI } from '@panwatch/api'
import '@/i18n'
import DataSourcesPage from './DataSources'

vi.mock('@panwatch/api', () => ({ fetchAPI: vi.fn(), resetDataSourcesToSeed: vi.fn() }))
const request = vi.mocked(fetchAPI)
const source = { id: 80, name: '长桥 ETF 成交额', type: 'etf_turnover', provider: 'longbridge',
  config: {}, enabled: true, priority: 0, supports_batch: false, test_symbols: ['510300'], connection_status: 'ready' }
beforeEach(() => { request.mockReset() })
afterEach(cleanup)

it('registers ETF turnover with connection management and its independent switch', async () => {
  request.mockImplementation(async (_path, options) => {
    if (options?.method === 'PUT') return { ...source, enabled: false }
    return [source]
  })
  render(<ConfirmProvider labels={{ title: "确认", confirm: "确定", cancel: "取消" }}><DataSourcesPage /></ConfirmProvider>)
  await screen.findByText('长桥 ETF 成交额')
  expect(screen.getByRole('link', { name: /管理长桥连接/ }).getAttribute('href')).toBe('/integrations/mcp')
  expect(screen.getByText('自动采集 · 持久化')).toBeTruthy()
  fireEvent.click(screen.getByRole('switch'))
  await waitFor(() => expect(request).toHaveBeenCalledWith('/datasources/80', { method: 'PUT', body: '{"enabled":false}' }))
})

it('tests only the selected source', async () => {
  request.mockImplementation(async (path) => path.endsWith('/test')
    ? { test_passed: true, source_name: source.name, source_type: source.type, provider: 'longbridge',
        count: 1, duration_ms: 5, items: [{ turnover_cny: 123 }], test_symbols: ['510300'], logs: [] }
    : [source])
  render(<ConfirmProvider labels={{ title: "确认", confirm: "确定", cancel: "取消" }}><DataSourcesPage /></ConfirmProvider>)
  await screen.findByText('长桥 ETF 成交额')
  fireEvent.click(screen.getByTitle('测试连接'))
  await waitFor(() => expect(request).toHaveBeenCalledWith('/datasources/80/test', { method: 'POST' }))
})
