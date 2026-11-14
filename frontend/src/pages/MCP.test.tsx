import { StrictMode } from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { ConfirmProvider } from '@panwatch/base-ui/components/ui/confirm-dialog'
import { fetchAPI } from '@panwatch/api/client'
import i18n from '@/i18n'
import MCPPage from './MCP'

vi.mock('@panwatch/api/client', () => ({ fetchAPI: vi.fn() }))
const request = vi.mocked(fetchAPI)
const BASE = '/mcp-connections/longbridge'
const STORAGE = 'panwatch-longbridge-oauth'
const initial = { id: 'longbridge', region: 'cn', endpoint: 'https://mcp.longbridge.cn',
  authorized: false, enabled: false, pending: false, tools: [], checked_at: null, error_code: '',
  docs_url: 'https://open.longbridge.com/zh-CN/docs/mcp' }
const authorized = { ...initial, authorized: true }
const tested = { ...authorized, checked_at: 1794670000, tools: [{ name: 'quote', title: ['行情快照', 'Quotes'] }] }
function mount(path = '/integrations/mcp') {
  return render(<StrictMode><MemoryRouter initialEntries={[path]}><ConfirmProvider
    labels={{ title: '确认', confirm: '确定', cancel: '取消' }}><MCPPage /></ConfirmProvider></MemoryRouter></StrictMode>)
}
beforeEach(() => { request.mockReset(); sessionStorage.clear() })
afterEach(cleanup)

describe('built-in MCP connections', () => {
  it('shows only the built-in provider and prevents use before authorization', async () => {
    request.mockResolvedValue({ items: [initial] })
    mount()
    await screen.findByRole('heading', { name: '长桥 Longbridge' })
    expect(screen.getByRole('switch').hasAttribute('disabled')).toBe(true)
    expect(screen.getByRole('button', { name: '前往长桥授权' })).toBeTruthy()
    expect(screen.queryByRole('textbox')).toBeNull()
    expect(screen.queryByRole('button', { name: /安装|添加/ })).toBeNull()
  })
  it('requires discovery before enabling and preserves server-returned state', async () => {
    request.mockResolvedValue({ items: [authorized] })
    mount()
    await screen.findByRole('button', { name: '检测连接' })
    expect(screen.getByRole('switch').hasAttribute('disabled')).toBe(true)
    request.mockResolvedValueOnce(tested)
    fireEvent.click(screen.getByRole('button', { name: '检测连接' }))
    await screen.findByText('行情快照')
    await waitFor(() => expect(screen.getByRole('switch').hasAttribute('disabled')).toBe(false))
    request.mockResolvedValueOnce({ ...tested, enabled: true })
    fireEvent.click(screen.getByRole('switch'))
    await waitFor(() => expect(screen.getByRole('switch').getAttribute('aria-checked')).toBe('true'))
    expect(request).toHaveBeenLastCalledWith(BASE, expect.objectContaining({ method: 'PUT', body: '{"enabled":true}' }))
  })
  it('allows cancelling disconnect and requires explicit confirmation', async () => {
    request.mockResolvedValue({ items: [tested] })
    mount()
    fireEvent.click(await screen.findByRole('button', { name: '断开连接' }))
    await screen.findByRole('dialog')
    expect(document.activeElement?.textContent).toBe('取消')
    fireEvent.click(screen.getByRole('button', { name: '取消' }))
    expect(request.mock.calls.some(([, options]) => options?.method === 'DELETE')).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: '断开连接' }))
    request.mockResolvedValueOnce(initial)
    fireEvent.click(await screen.findByRole('button', { name: '确定' }))
    await screen.findByText('未授权')
    expect(request).toHaveBeenLastCalledWith(BASE, expect.objectContaining({ method: 'DELETE' }))
  })
  it('consumes the browser-bound callback only once under StrictMode', async () => {
    sessionStorage.setItem(STORAGE, JSON.stringify({ state: 'bound-state', browserKey: 'bound-browser' }))
    request.mockImplementation(async path => path === BASE + '/callback' ? authorized : { items: [authorized] })
    mount('/integrations/mcp/callback?code=one-use-code&state=bound-state')
    await screen.findByRole('button', { name: '检测连接' })
    const callbacks = request.mock.calls.filter(([path]) => path === BASE + '/callback')
    expect(callbacks).toHaveLength(1)
    expect(JSON.parse(callbacks[0][1]!.body as string)).toEqual({ state: 'bound-state', browser_key: 'bound-browser', code: 'one-use-code', error: null })
    expect(sessionStorage.getItem(STORAGE)).toBeNull()
    expect(window.location.search).toBe('')
  })
  it('rejects an unbound callback without exchanging a code', async () => {
    mount('/integrations/mcp/callback?code=foreign-code&state=foreign-state')
    await screen.findByRole('alert')
    expect(request).not.toHaveBeenCalled()
  })
  it('exposes load errors and recovers through retry', async () => {
    request.mockRejectedValue(new Error('Connection unavailable'))
    mount()
    await screen.findByRole('alert')
    request.mockResolvedValue({ items: [initial] })
    fireEvent.click(screen.getByRole('button', { name: '返回并重试' }))
    await screen.findByText('未授权')
    expect(screen.queryByRole('alert')).toBeNull()
  })
  it('renders the English configuration and tool titles', async () => {
    await i18n.changeLanguage('en-US')
    request.mockResolvedValue({ items: [tested] })
    mount()
    await screen.findByText('Quotes')
    expect(screen.getByRole('button', { name: 'Test connection' })).toBeTruthy()
    expect(screen.queryByText('行情快照')).toBeNull()
  })
})
