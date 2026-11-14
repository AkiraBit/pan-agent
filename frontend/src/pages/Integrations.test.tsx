import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom'
import { ConfirmProvider } from '@panwatch/base-ui/components/ui/confirm-dialog'
import { fetchAPI } from '@panwatch/api/client'
import i18n from '@/i18n'
import IntegrationsPage from './Integrations'

vi.mock('@panwatch/api/client', () => ({ fetchAPI: vi.fn() }))
const request = vi.mocked(fetchAPI)
const connection = { id: 'longbridge', region: 'cn', endpoint: 'https://mcp.longbridge.cn', authorized: true, enabled: true,
  pending: false, tools: [], checked_at: 1794670000, error_code: '', account_label: 'demo@example.com(Demo)', connected_at: 1794667900,
  server_version: '0.16.4', docs_url: 'https://open.longbridge.com/zh-CN/docs/mcp' }
const skill = { id: 'longbridge', title: ['长桥总览', 'Longbridge overview'], description: ['查询与分析', 'Queries and analysis'],
  support: 'partial', upstream_version: null, bundled_file_count: 9,
  capabilities: [{ title: ['行情查询', 'Market queries'], tools: ['quote'], tools_present: true }],
  unsupported_capabilities: [['交易操作', 'Trading']], workflow: [['获取数据', 'Retrieve data']], examples: [['查询 AAPL 报价', 'Get AAPL quotes']], version: '1.0.0', upstream_revision: '38900e9884027782c1f4e480b451d5f55a479d95',
  source_url: 'https://github.com/longbridge/skills/blob/38900e9884027782c1f4e480b451d5f55a479d95/skills/longbridge/SKILL.md',
  docs_url: 'https://open.longbridge.com/zh-CN/skill', enabled: false, available: false, connection_status: 'ready',
  tools: [{ name: 'quote', title: ['行情快照', 'Quotes'] }] }
const catalog = [skill, ...[
  ['market-data', '行情数据', 'Market data'], ['technical', '技术分析', 'Technical analysis'],
  ['fundamentals', '基本面', 'Fundamentals'], ['portfolio', '账户与持仓', 'Portfolio & account'],
  ['content', '新闻与公告', 'News & filings'], ['intel', '市场情报', 'Market intelligence'],
  ['derivatives', '期权与窝轮', 'Derivatives'], ['research', '机构研究', 'Institutional research'],
  ['earnings', '财报分析', 'Earnings analysis'], ['quant', '量化策略', 'Quantitative strategies'],
  ['value-investing', '价值投资', 'Value investing'], ['watchlist', '自选与提醒', 'Watchlist & alerts'],
].map(([id, zh, en], index) => ({ ...skill, id: `longbridge-${id}`, title: [zh, en],
  support: index < 4 ? 'partial' : 'unsupported', capabilities: index < 4 ? skill.capabilities : [],
  workflow: index < 4 ? skill.workflow : [], examples: index < 4 ? skill.examples : [], version: index < 4 ? '1.0.0' : null }))]
function LocationProbe() {
  const location = useLocation(), navigate = useNavigate()
  return <><output data-testid="location">{location.pathname + location.search}</output><button onClick={() => navigate(-1)}>Back</button></>
}
function mount(path = '/integrations/mcp') {
  return render(<MemoryRouter initialEntries={[path]}><ConfirmProvider labels={{ title: '确认', confirm: '确定', cancel: '取消' }}>
    <IntegrationsPage /><LocationProbe />
  </ConfirmProvider></MemoryRouter>)
}
beforeEach(async () => {
  await i18n.changeLanguage('zh-CN')
  request.mockReset()
  request.mockImplementation(async path => ({ items: path === '/builtin-skills' ? catalog : [connection] }))
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('MCP and Skills', () => {
  it('renames the page and switches tabs with URL state and browser back', async () => {
    mount()
    expect(screen.getByRole('heading', { name: 'MCP & 技能' })).toBeTruthy()
    await screen.findByText('demo@example.com(Demo)')
    fireEvent.mouseDown(screen.getByRole('tab', { name: '技能' }), { button: 0, ctrlKey: false })
    await screen.findByRole('heading', { name: '长桥总览' })
    expect(screen.getByTestId('location').textContent).toBe('/integrations/mcp?tab=skills')
    expect(screen.queryByText('demo@example.com(Demo)')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Back' }))
    await screen.findByText('demo@example.com(Demo)')
    expect(screen.getByRole('tab', { name: 'MCP' }).getAttribute('aria-selected')).toBe('true')
  })

  it('opens the skills tab directly and shows provenance, supported capabilities and examples', async () => {
    mount('/integrations/mcp?tab=skills')
    await screen.findByRole('heading', { name: '长桥总览' })
    expect(screen.getByRole('tab', { name: '技能' }).getAttribute('aria-selected')).toBe('true')
    expect(screen.getByText('1.0.0')).toBeTruthy()
    expect(screen.getByRole('link', { name: '38900e9' }).getAttribute('href')).toBe(skill.source_url)
    expect(screen.getByText('行情快照')).toBeTruthy()
    expect(screen.getByText('PanWatch 适配版')).toBeTruthy()
    expect(screen.getByRole('heading', { name: '试着这样问' })).toBeTruthy()
    expect(screen.getByRole('link', { name: '管理连接' }).getAttribute('href')).toBe('/integrations/mcp')
    expect(screen.queryByRole('button', { name: /安装|上传/ })).toBeNull()
    expect(request).toHaveBeenCalledTimes(1)
  })

  it('lists all 13 skills and restores selection from the URL, including unsupported capabilities', async () => {
    mount('/integrations/mcp?tab=skills&skill=longbridge-derivatives')
    await screen.findByRole('heading', { name: '期权与窝轮' })
    expect(screen.getByText('13 个技能 · 5 个部分支持 · 8 个尚未支持')).toBeTruthy()
    expect(screen.getByRole('switch', { name: '启用技能' }).hasAttribute('disabled')).toBe(true)
    expect(screen.getByText('官方内容已内置，所需能力尚未接入，暂不能启用。')).toBeTruthy()
    expect(screen.queryByRole('link', { name: '前往助手' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /技术分析/ }))
    await screen.findByRole('heading', { name: '技术分析' })
    expect(screen.getByTestId('location').textContent).toContain('skill=longbridge-technical')
    expect(screen.getByRole('switch', { name: '启用技能' }).hasAttribute('disabled')).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: 'Back' }))
    await screen.findByRole('heading', { name: '期权与窝轮' })
  })

  it('shows official source as inert text, and clears it when selecting another skill', async () => {
    mount('/integrations/mcp?tab=skills')
    const open = await screen.findByRole('button', { name: '查看官方原文' })
    request.mockResolvedValueOnce({ content: '# Official <script>alert(1)</script>' })
    fireEvent.click(open)
    await screen.findByText('# Official <script>alert(1)</script>')
    expect(request).toHaveBeenLastCalledWith('/builtin-skills/longbridge/source')
    expect(document.querySelector('pre script')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /技术分析/ }))
    await screen.findByRole('heading', { name: '技术分析' })
    expect(screen.queryByText('# Official <script>alert(1)</script>')).toBeNull()
    expect(screen.getByRole('button', { name: '查看官方原文' }).getAttribute('aria-expanded')).toBe('false')
  })

  it('changes only the selected skill setting', async () => {
    mount('/integrations/mcp?tab=skills&skill=longbridge-market-data')
    const toggle = await screen.findByRole('switch', { name: '启用技能' })
    await waitFor(() => expect(toggle.hasAttribute('disabled')).toBe(false))
    request.mockResolvedValueOnce({ ...catalog[1], enabled: true, available: true })
    fireEvent.click(toggle)
    await screen.findByRole('link', { name: '前往助手' })
    expect(request).toHaveBeenLastCalledWith('/builtin-skills/longbridge-market-data', { method: 'PUT', body: '{"enabled":true}' })
    fireEvent.click(screen.getByRole('button', { name: /长桥总览/ }))
    expect(screen.getByRole('switch', { name: '启用技能' }).getAttribute('aria-checked')).toBe('false')
  })

  it('persists enabling through the API without changing the MCP grant', async () => {
    mount('/integrations/mcp?tab=skills')
    const toggle = await screen.findByRole('switch', { name: '启用技能' })
    await waitFor(() => expect(toggle.hasAttribute('disabled')).toBe(false))
    request.mockResolvedValueOnce({ ...skill, enabled: true, available: true })
    fireEvent.click(toggle)
    await screen.findByRole('link', { name: '前往助手' })
    expect(toggle.getAttribute('aria-checked')).toBe('true')
    expect(request).toHaveBeenLastCalledWith('/builtin-skills/longbridge', { method: 'PUT', body: '{"enabled":true}' })
    expect(request.mock.calls.some(([path]) => path.includes('authorize'))).toBe(false)
  })

  it('keeps the last saved setting when saving fails', async () => {
    mount('/integrations/mcp?tab=skills')
    const toggle = await screen.findByRole('switch', { name: '启用技能' })
    await waitFor(() => expect(toggle.hasAttribute('disabled')).toBe(false))
    request.mockRejectedValueOnce(new Error('Save failed'))
    fireEvent.click(toggle)
    await screen.findByRole('alert')
    expect(toggle.getAttribute('aria-checked')).toBe('false')
  })

  it.each(['authorization_required', 'mcp_disabled', 'test_required'])('shows dependency guidance for %s', async status => {
    request.mockResolvedValue({ items: [{ ...skill, enabled: true, connection_status: status }] })
    mount('/integrations/mcp?tab=skills')
    await screen.findByText(i18n.t(`configuration:skills.${status}` as 'configuration:skills.test_required'))
    expect(screen.queryByRole('link', { name: '前往助手' })).toBeNull()
    expect(screen.getByRole('link', { name: '管理连接' })).toBeTruthy()
  })

  it('recovers from a failed catalog load', async () => {
    request.mockRejectedValueOnce(new Error('Offline'))
    mount('/integrations/mcp?tab=skills')
    fireEvent.click(await screen.findByRole('button', { name: '重新加载' }))
    await screen.findByRole('heading', { name: '长桥总览' })
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('keeps the OAuth callback on MCP even when a skills tab parameter is present', async () => {
    sessionStorage.clear()
    mount('/integrations/mcp/callback?tab=skills&code=unused&state=unbound')
    await screen.findByRole('alert')
    expect(screen.getByRole('tab', { name: '技能' }).hasAttribute('disabled')).toBe(true)
    expect(screen.getByRole('tab', { name: 'MCP' }).getAttribute('aria-selected')).toBe('true')
    expect(request).not.toHaveBeenCalled()
  })

  it('renders the English skills page', async () => {
    await i18n.changeLanguage('en-US')
    mount('/integrations/mcp?tab=skills')
    await screen.findByRole('heading', { name: 'Longbridge overview' })
    expect(screen.getByRole('heading', { name: 'MCP & Skills' })).toBeTruthy()
    expect(screen.getByText('Quotes')).toBeTruthy()
    expect(screen.getByRole('switch', { name: 'Enable skill' })).toBeTruthy()
  })
})
