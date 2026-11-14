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
  account_label: '', connected_at: null, server_version: '',
  docs_url: 'https://open.longbridge.com/zh-CN/docs/mcp' }
const authorized = { ...initial, authorized: true }
const tested = { ...authorized, checked_at: 1794670000, connected_at: 1794667900, account_label: 'HK · ••••1234', server_version: '2.7.1',
  tools: [{ name: 'quote', title: ['行情快照', 'Quotes'], description: 'Returns real-time quotes for the requested symbols.' }] }
function mount(path = '/integrations/mcp') {
  return render(<StrictMode><MemoryRouter initialEntries={[path]}><ConfirmProvider
    labels={{ title: '确认', confirm: '确定', cancel: '取消' }}><MCPPage /></ConfirmProvider></MemoryRouter></StrictMode>)
}
beforeEach(() => { request.mockReset(); sessionStorage.clear() })
afterEach(() => { cleanup(); vi.restoreAllMocks() })

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
    await screen.findAllByText('未授权')
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
    await screen.findAllByText('未授权')
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

  it('shows service navigation, official icons, account metadata and upstream tool descriptions', async () => {
    request.mockResolvedValue({ items: [tested] })
    mount()
    await screen.findByText('HK · ••••1234')
    expect(screen.getByRole('navigation', { name: '内置 MCP' })).toBeTruthy()
    expect(screen.getByRole('link', { name: /长桥 Longbridge/ }).getAttribute('aria-current')).toBe('page')
    expect(screen.getAllByAltText('Longbridge').every(img => img.getAttribute('src')?.startsWith('https://assets.lbkrs.com/'))).toBe(true)
    expect(screen.getByText('2.7.1')).toBeTruthy()
    expect(screen.getByText('关联时间')).toBeTruthy()
    expect(screen.queryByText('此前未记录')).toBeNull()
    expect(screen.getByText(tested.tools[0].description)).toBeTruthy()
    expect(screen.getByText('quote')).toBeTruthy()
  })

  it('does not fabricate legacy connection timestamps, server versions or descriptions', async () => {
    request.mockResolvedValue({ items: [{ ...tested, connected_at: null, account_label: '', server_version: '',
      tools: [{ ...tested.tools[0], description: '' }] }] })
    mount()
    await screen.findByText('此前未记录')
    expect(screen.getByText('服务端未提供')).toBeTruthy()
    expect(screen.getByText('暂未获取，请检测连接')).toBeTruthy()
    expect(screen.getByText('此工具暂未提供介绍。')).toBeTruthy()
  })

  it('displays the provider email and account name when available', async () => {
    request.mockResolvedValue({ items: [{ ...tested, account_label: 'demo@example.com(Demo Account)' }] })
    mount()
    await screen.findByText('demo@example.com(Demo Account)')
    expect(screen.queryByText('长桥未提供邮箱，显示可用账号信息；账户编号已脱敏。')).toBeNull()
  })

  it('collapses overflowing descriptions to one line and supports expand/collapse', async () => {
    // jsdom has no text layout; supply a two-line measurement for this paragraph.
    vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockReturnValue(48)
    const computedStyle = window.getComputedStyle.bind(window)
    vi.spyOn(window, 'getComputedStyle').mockImplementation((element, pseudo) => {
      const style = computedStyle(element, pseudo)
      if (element.tagName === 'P') Object.defineProperty(style, 'lineHeight', { value: '24px', configurable: true })
      return style
    })
    request.mockResolvedValue({ items: [tested] })
    mount()
    const expand = await screen.findByRole('button', { name: '展开' })
    const description = screen.getByText(tested.tools[0].description)
    expect(description.className).toContain('line-clamp-1')
    fireEvent.click(expand)
    expect(description.className).not.toContain('line-clamp-1')
    fireEvent.click(screen.getByRole('button', { name: '收起' }))
    expect(description.className).toContain('line-clamp-1')
  })
})
