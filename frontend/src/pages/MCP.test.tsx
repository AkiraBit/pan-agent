import { StrictMode } from 'react'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { ConfirmProvider } from '@panwatch/base-ui/components/ui/confirm-dialog'
import { fetchAPI } from '@panwatch/api/client'
import i18n from '@/i18n'
import MCPPage from './MCP'
import DataProvidersSettings from '@/components/integrations/DataProvidersSettings'

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

describe('Fuyao connection', () => {
  const endpoint = '/mcp-connections/fuyao'
  const service = { id: 'a-share', endpoint: 'https://fuyao.aicubes.cn/mcp/a-share', enabled: false, checked_at: null, tools: [] }

  it('links to the shared settings card and blocks MCP testing without a key', async () => {
    request.mockResolvedValue({ configured: false, services: [service] })
    mount('/integrations/mcp?provider=fuyao')
    expect((await screen.findByRole('link', { name: '配置同花顺 API Key' })).getAttribute('href')).toBe('/settings#sec-data-providers')
    expect((await screen.findByRole('button', { name: '检测连接' })).hasAttribute('disabled')).toBe(true)
    expect(screen.getByRole('switch').hasAttribute('disabled')).toBe(true)
  })

  it('tests the selected service before enabling it for the assistant', async () => {
    request.mockResolvedValue({ configured: true, services: [service] })
    mount('/integrations/mcp?provider=fuyao')
    const test = await screen.findByRole('button', { name: '检测连接' })
    const enable = screen.getByRole('switch')
    expect(enable.hasAttribute('disabled')).toBe(true)
    const discovered = { ...service, checked_at: 1794670000, tools: [{ name: 'get_a_share_prices_snapshot', title: '行情快照' }] }
    request.mockResolvedValueOnce({ configured: true, services: [discovered] })
    fireEvent.click(test)
    await screen.findByText('查看查询工具（1）')
    expect(request).toHaveBeenLastCalledWith(endpoint + '/a-share/test', expect.objectContaining({ method: 'POST' }))
    request.mockResolvedValueOnce({ configured: true, services: [{ ...discovered, enabled: true }] })
    fireEvent.click(enable)
    await waitFor(() => expect(enable.getAttribute('aria-checked')).toBe('true'))
    expect(request).toHaveBeenLastCalledWith(endpoint + '/a-share', expect.objectContaining({ method: 'PUT', body: '{"enabled":true}' }))
  })
})

describe('data provider settings', () => {
  it('adds a key, displays its masked value, and clears it from the edit dialog', async () => {
    request.mockResolvedValue({ configured: false, masked_key: null })
    render(<ConfirmProvider labels={{ title: '确认', confirm: '确定', cancel: '取消' }}><DataProvidersSettings /></ConfirmProvider>)
    const card = within(screen.getByRole('region', { name: 'FTShare' }))
    const path = '/settings/data-providers/ftshare'
    fireEvent.click(await card.findByRole('button', { name: '添加 FTShare API Key' }))
    const add = within(await screen.findByRole('dialog', { name: '添加 FTShare API Key' }))
    const input = add.getByLabelText('API Key', { exact: true }) as HTMLInputElement
    expect(input.type).toBe('password')
    request.mockResolvedValueOnce({ configured: true, masked_key: 'ftshare_sk_V****Lm10' })
    fireEvent.change(input, { target: { value: ' ftshare_sk_V.not-a-real-key.Lm10 ' } })
    fireEvent.click(add.getByRole('button', { name: '保存' }))
    await card.findByText('ftshare_sk_V****Lm10')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(request).toHaveBeenLastCalledWith(path, { method: 'PUT', body: '{"api_key":"ftshare_sk_V.not-a-real-key.Lm10"}' })
    fireEvent.click(card.getByRole('button', { name: '修改 FTShare API Key' }))
    const edit = within(await screen.findByRole('dialog', { name: '修改 FTShare API Key' }))
    expect((edit.getByLabelText('API Key', { exact: true }) as HTMLInputElement).value).toBe('')
    fireEvent.click(edit.getByRole('button', { name: '清除 Key' }))
    request.mockResolvedValueOnce({ configured: false, masked_key: null })
    fireEvent.click(await screen.findByRole('button', { name: '确定' }))
    await card.findByText('未保存')
    expect(card.queryByText('ftshare_sk_V****Lm10')).toBeNull()
    expect(request).toHaveBeenLastCalledWith(path, { method: 'DELETE' })
  })

  it('discards a canceled replacement for an existing key', async () => {
    request.mockImplementation(async (path) => path.endsWith('/fuyao')
      ? { configured: true, masked_key: 'fixt****9876' } : { configured: false, masked_key: null })
    render(<DataProvidersSettings />)
    const card = within(screen.getByRole('region', { name: '同花顺（扶摇）' }))
    await card.findByText('fixt****9876')
    const pencil = card.getByRole('button', { name: '修改 同花顺（扶摇） API Key' })
    fireEvent.click(pencil)
    const edit = within(await screen.findByRole('dialog'))
    fireEvent.change(edit.getByLabelText('API Key', { exact: true }), { target: { value: 'not-saved' } })
    fireEvent.click(edit.getByRole('button', { name: '取消' }))
    fireEvent.click(pencil)
    expect((within(await screen.findByRole('dialog')).getByLabelText('API Key', { exact: true }) as HTMLInputElement).value).toBe('')
    expect(request.mock.calls.some(([, options]) => options?.method === 'PUT')).toBe(false)
  })
})

describe('built-in MCP connections', () => {
  it('switches an authorized node without reauthorization and keeps the account and enable state', async () => {
    request.mockResolvedValue({ items: [{ ...tested, enabled: true }] })
    mount()
    const select = await screen.findByRole('combobox', { name: '连接节点' })
    await waitFor(() => expect(select.hasAttribute('disabled')).toBe(false))
    fireEvent.keyDown(select, { key: 'ArrowDown' })
    request.mockResolvedValueOnce({ ...tested, enabled: true, region: 'global', endpoint: 'https://mcp.longbridge.com', server_version: '2.8.0' })
    fireEvent.click(await screen.findByRole('option', { name: '全球' }))
    await screen.findByText('https://mcp.longbridge.com')
    expect(select.textContent).toBe('全球')
    expect(screen.getByText('HK · ••••1234')).toBeTruthy()
    expect(screen.getByText('2.8.0')).toBeTruthy()
    expect(screen.getByRole('switch').getAttribute('aria-checked')).toBe('true')
    expect(request).toHaveBeenLastCalledWith(BASE + '/region', expect.objectContaining({ method: 'PUT', body: '{"region":"global"}' }))
    expect(request.mock.calls.some(([path]) => path === BASE + '/authorize')).toBe(false)
  })

  it('keeps the saved node when switching fails and allows retry', async () => {
    request.mockResolvedValue({ items: [tested] })
    mount()
    const select = await screen.findByRole('combobox', { name: '连接节点' })
    await waitFor(() => expect(select.hasAttribute('disabled')).toBe(false))
    fireEvent.keyDown(select, { key: 'ArrowDown' })
    request.mockRejectedValueOnce(new Error('Target unavailable'))
    fireEvent.click(await screen.findByRole('option', { name: '全球' }))
    await screen.findByRole('alert')
    expect(select.textContent).toBe('中国大陆')
    expect(screen.getByText('https://mcp.longbridge.cn')).toBeTruthy()
    expect(screen.getByText('HK · ••••1234')).toBeTruthy()
    expect(select.hasAttribute('disabled')).toBe(false)
  })

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
