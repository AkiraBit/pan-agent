import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { ConfirmProvider } from '@panwatch/base-ui/components/ui/confirm-dialog'
import { ToastProvider } from '@panwatch/base-ui/components/ui/toast'
import { emotionApi, type EmotionPublication, type EmotionWorkspace, type SessionValidation } from '@panwatch/api/emotion'
import i18n from '@/i18n'
import EmotionWorkbench from './EmotionWorkbench'

vi.mock('@panwatch/api/emotion', () => ({ emotionApi: {
  workspace: vi.fn(), publication: vi.fn(), run: vi.fn(), cancel: vi.fn(),
  sessionValidation: vi.fn(), armSessionValidation: vi.fn(), lifecycle: vi.fn(), monitor: vi.fn(), review: vi.fn(), saveAuctionSource: vi.fn(),
  settings: vi.fn(), context: vi.fn(), contextStatus: vi.fn(),
} }))
const empty: EmotionWorkspace = { publication: null, settings: { focus_symbols: [], schedule_enabled: false, schedule_time: '08:45', language: 'zh-CN', monitoring_enabled: false, monitor_interval_seconds: 30, postmarket_enabled: false, postmarket_time: '15:10' }, target_trade_date: '2026-11-16', server_time: '2026-11-14T00:00:00Z', input_version: 0, history: [], runs: [], notes: [] }
const publication: EmotionPublication = {
  schema_version: '1.0', id: 'pub1', revision: 1, parent_revision: 0, input_version: 0, run_id: 'run1', published_at: '2026-11-14T00:00:00Z', model_label: 'test-only',
  target_trade_date: '2026-11-16', market_as_of: '2026-11-13', knowledge_cutoff: '2026-11-14T00:00:00Z', continuous_monitoring: false,
  analysis: { title: '保留的原始判断', summary: '修复与独强需要竞争验证。', stage: 'unknown', supports: [{ text: '仅有采样证据。', evidence_ids: ['q1'] }], counters: [{ text: '缺少广度响应。', evidence_ids: ['q1'] }], cycles: [], watchlist: [], scenarios: [],
    conditions: [{ id: 'c1', title: '开盘联合响应', subject: null, window: 'opening', criterion: '检查多个分支。', invalidation: '只有核心独强。', evidence_ids: ['q1'], expression: null }],
    memory_summary: '旧假设需要再验证。', open_questions: ['分支是否响应？'], changes: ['首次观察。'], blocks: [
      { id: 'v1', page: 'overview', kind: 'verdict', title: '本轮判断', entity_ids: [] },
      { id: 'c1', page: 'playbook', kind: 'conditions', title: '观察条件', entity_ids: [] },
    ] },
  facts: { collected_at: '2026-11-14T00:00:00Z', reference_trade_date: '2026-11-13', phase: 'closed', coverage: { status: 'partial', count: 1, expected: 5000 }, quotes: [],
    evidence: [{ id: 'q1', kind: 'quote', title: '行情证据', source: 'test-only', content: { price: 10.5 }, observed_at: '2026-11-14T00:00:00Z', published_at: '2026-11-13T07:00:00Z', url: 'https://example.com/source', status: 'available', content_hash: 'test-hash' }], capabilities: { auction: false }, snapshot: { market: { rising: 1, falling: 0, valid: 1, median: 1 }, sentiment: { counts: {}, break_rate: null, yesterday_mean: null } } },
  context: [], memory_input: [], condition_states: [{ id: 'c1', state: 'waiting', reason: 'window_not_reached', observed_value: null, observed_at: '2026-11-14T00:00:00Z' }],
}
function mount(path = '/short-term') {
  return render(<MemoryRouter initialEntries={[path]}><ToastProvider><ConfirmProvider labels={{ title: '确认', cancel: '取消', confirm: '确定' }}><EmotionWorkbench /></ConfirmProvider></ToastProvider></MemoryRouter>)
}
beforeEach(async () => { vi.clearAllMocks(); await i18n.changeLanguage('zh-CN'); await i18n.loadNamespaces('emotion'); vi.mocked(emotionApi.workspace).mockResolvedValue(empty); vi.mocked(emotionApi.lifecycle).mockResolvedValue({ monitor: null, sample_count: 0, latest: null, timeline: [], review: null, auction_source: { enabled: false, endpoint: '', provider_name: 'licensed_gateway', has_api_key: false } }) })
afterEach(cleanup)

describe('sentiment workbench user entry', () => {
  it('starts an analysis through the production API contract without fabricated publication', async () => {
    mount()
    await screen.findByText('开始第一份真实市场分析')
    fireEvent.click(screen.getByRole('button', { name: '生成盘前预案' }))
    await waitFor(() => expect(emotionApi.run).toHaveBeenCalledWith(expect.objectContaining({ target_trade_date: '2026-11-16', language: 'zh-CN', request_key: expect.any(String) })))
    expect(screen.queryByText('保留的原始判断')).toBeNull()
    expect(emotionApi.run).toHaveBeenCalledTimes(1)
  })

  it('saves an unresolved constraint and restores it on the normal read path', async () => {
    mount()
    await screen.findByText('开始第一份真实市场分析')
    fireEvent.click(screen.getAllByRole('button', { name: '补充上下文' })[0])
    fireEvent.change(screen.getByLabelText('事件、约束或不同解释'), { target: { value: '监管线索待核验' } })
    vi.mocked(emotionApi.workspace).mockResolvedValue({ ...empty, input_version: 1, notes: [{ id: 'n1', content: '监管线索待核验', source_url: null, created_at: empty.server_time, status: 'open', verification: 'user_unverified' }] })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => expect(emotionApi.context).toHaveBeenCalledWith('监管线索待核验', null))
    await screen.findByText('监管线索待核验')
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('retains the good version after failure and exposes host-owned capability gaps', async () => {
    vi.mocked(emotionApi.workspace).mockResolvedValue({ ...empty, publication, runs: [{ id: 'r2', status: 'failed', target_trade_date: '2026-11-16', created_at: empty.server_time, finished_at: empty.server_time, base_revision: 1, model_label: null, error_code: 'market_data_stale', publication_id: null, events: [] }] })
    mount()
    await screen.findByText('保留的原始判断')
    expect(screen.getByText('行情日期不匹配，已暂停生成新判断。')).toBeTruthy()
    expect(screen.getByText(/预案发布后冻结/)).toBeTruthy()
    fireEvent.click(screen.getAllByRole('button', { name: '行情证据' })[0])
    expect(screen.getByRole('dialog')).toBeTruthy()
    expect(screen.getByRole('link', { name: /打开原始来源/ }).getAttribute('href')).toBe('https://example.com/source')
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('renders next-session observations as waiting, and preserves the selected historical revision', async () => {
    vi.mocked(emotionApi.workspace).mockResolvedValue({ ...empty, publication: { ...publication, id: 'pub2', revision: 2 } })
    vi.mocked(emotionApi.publication).mockResolvedValue(publication)
    mount('/short-term/playbook?publication=pub1')
    await screen.findByText('开盘联合响应')
    expect(screen.getByText('待观察')).toBeTruthy()
    expect(screen.queryByText('采样已满足')).toBeNull()
    expect(screen.getByText('正在查看历史版本；这里保留的是当时判断。')).toBeTruthy()
    expect(screen.getByRole('button', { name: '版本 1' })).toBeTruthy()
    expect(emotionApi.publication).toHaveBeenCalledWith('pub1', expect.any(AbortSignal))
  })

  it('loads English and requires explicit confirmation before cancellation', async () => {
    await i18n.changeLanguage('en-US')
    vi.mocked(emotionApi.workspace).mockResolvedValue({ ...empty, runs: [{ id: 'active1', status: 'running', target_trade_date: '2026-11-16', created_at: empty.server_time, finished_at: null, base_revision: 0, model_label: null, error_code: null, publication_id: null, events: [] }] })
    mount()
    const cancel = await screen.findByRole('button', { name: 'Stop this analysis' })
    fireEvent.click(cancel)
    expect(emotionApi.cancel).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '取消' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(emotionApi.cancel).not.toHaveBeenCalled()
  })
})

it('arms monitoring without mutating the frozen plan and shows missing auction explicitly', async () => {
  vi.mocked(emotionApi.workspace).mockResolvedValue({ ...empty, publication })
  mount('/short-term/monitor')
  await screen.findByText('待配置')
  fireEvent.click(screen.getByRole('button', { name: '启动监测' }))
  await waitFor(() => expect(emotionApi.monitor).toHaveBeenCalledWith('pub1', true))
  expect(emotionApi.run).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '配置竞价源' }))
  const key = screen.getByLabelText('访问密钥（可选）')
  expect(key.getAttribute('type')).toBe('password')
  fireEvent.change(screen.getByLabelText('接口地址（HTTPS 或本机）'), { target: { value: 'https://gateway.example/auction' } })
  fireEvent.change(key, { target: { value: 'test-only-key' } })
  fireEvent.click(screen.getByRole('button', { name: '保存' }))
  await waitFor(() => expect(emotionApi.saveAuctionSource).toHaveBeenCalledWith(expect.objectContaining({ api_key: 'test-only-key', endpoint: 'https://gateway.example/auction' })))
})


it('keeps the armed day visible across trading days and confirms activation without configuring auction', async () => {
  const audit = { trade_date: '2026-11-16', next_trade_date: '2026-11-17', enabled: false, status: 'not_armed', heartbeat_at: null,
    server_time: empty.server_time, checkpoints: [{ id: 'auction', status: 'skipped', reason: 'auction_not_configured' }],
    warnings: ['auction_not_configured'], events: [], auction_configured: false, configured_stages_verified: false, natural_session_verified: false } as SessionValidation
  vi.mocked(emotionApi.workspace).mockResolvedValue({ ...empty, target_trade_date: '2026-11-17', validation_trade_date: '2026-11-16' })
  vi.mocked(emotionApi.sessionValidation).mockResolvedValue(audit)
  vi.mocked(emotionApi.armSessionValidation).mockResolvedValue({ ...audit, enabled: true, status: 'armed' })
  mount('/short-term/validation')
  await waitFor(() => expect(emotionApi.sessionValidation).toHaveBeenCalledWith('2026-11-16', expect.any(AbortSignal)))
  const arm = await screen.findByRole('button', { name: '启用此交易日验证' })
  fireEvent.click(arm)
  expect(emotionApi.armSessionValidation).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '取消' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(emotionApi.armSessionValidation).not.toHaveBeenCalled()
  fireEvent.click(arm)
  fireEvent.click(screen.getByRole('button', { name: '确定' }))
  await waitFor(() => expect(emotionApi.armSessionValidation).toHaveBeenCalledWith('2026-11-16', true))
  expect(emotionApi.saveAuctionSource).not.toHaveBeenCalled()
  expect(emotionApi.run).not.toHaveBeenCalled()
  expect(screen.queryByText('完整自然交易日已验证')).toBeNull()
})

it('renders exchange events as readable dates while keeping raw provider fields out of the ledger', async () => {
  vi.mocked(emotionApi.workspace).mockResolvedValue({ ...empty, publication: { ...publication, facts: { ...publication.facts, quotes: [], evidence: [{ id: 'reg:test', kind: 'regulatory_window', title: 'Test windows', source: 'exchange', observed_at: empty.server_time, content_hash: 'test', status: 'calculated_with_source_limits', published_at: null, url: null, content: {
    symbol: '002242.SZ', as_of: '2026-11-13', price_basis: { method: 'raw_with_sina_qfq_factors', range_start: '2026-09-11', range_end: '2026-11-13', row_count: 41 }, status: 'calculated_with_source_limits', reset_verification: 'exchange_confirmed_history', gaps: [], windows: [], reset_records: [],
    repeat_events: { up: 1, down: 0, threshold: 4 }, special_days: { excluded: {}, suspended: {}, ex_right: [] }, trading_constraints: [{ kind: 'scheduled_suspension', start: '2026-11-16', resumption_date: null, source_url: 'https://static.cninfo.com.cn/hold.pdf', event_id: 'hold' }], coverage: { status: 'complete', range_start: '2026-08-06', range_end: '2026-11-14', unresolved: [], reconciliations: [{ url: 'https://static.cninfo.com.cn/conflict.pdf', period_start: '2026-09-27', period_end: '2026-09-28', official_period_start: '2026-09-24', official_period_end: '2026-09-28' }] },
    events: [{ id: 'exchange1', kind: 'ordinary', period_start: '2026-11-11', period_end: '2026-11-12', effective_date: '2026-11-13', exchange_publication_date: '2026-11-12', authority: 'exchange_publication', document_title: '交易所披露记录', source_url: 'https://www.szse.cn/disclosure/deal/public/', known_at: empty.server_time, excerpt: '{"provider_internal_field":"raw audit only"}' }],
  } }] } } })
  mount('/short-term/evidence')
  await screen.findByText('交易所披露记录')
  expect(screen.getByText('异动区间 2026-11-11 至 2026-11-12；交易所公布日 2026-11-12；按规则从 2026-11-13 起重算。')).toBeTruthy()
  expect(screen.queryByText(/provider_internal_field/)).toBeNull()
  expect(screen.getByText(/腾讯未复权日线 \/ 新浪逐日复权因子/)).toBeTruthy()
  expect(screen.getByText(/自 2026-11-16 起停牌；复牌日期：尚未公告/)).toBeTruthy()
  expect(screen.getByText(/原公告区间 2026-09-27—2026-09-28 与交易日历不符/)).toBeTruthy()
})
