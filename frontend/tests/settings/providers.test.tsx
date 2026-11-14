import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchAPI } from '@panwatch/api'
import SettingsPage from '@/pages/Settings'

vi.mock('@panwatch/api', () => ({ fetchAPI: vi.fn() }))
vi.mock('@/components/PatSection', () => ({ default: () => null }))
vi.mock('@/components/UserAvatar', () => ({ UserAvatar: () => null }))
vi.mock('@/components/onboarding/GuidedTour', () => ({ useGuidedTour: () => null }))
vi.mock('@/hooks/use-avatar', () => ({ useAvatar: () => ({ avatar: null }), saveAvatar: vi.fn(), fileToAvatarDataUrl: vi.fn() }))
vi.mock('@/hooks/use-market-colors', () => ({ useMarketColors: () => ({ preference: 'auto', setPreference: vi.fn() }) }))
vi.mock('@panwatch/base-ui/components/ui/confirm-dialog', () => ({ useConfirm: () => vi.fn() }))
vi.mock('@panwatch/base-ui/components/ui/toast', () => ({ useToast: () => vi.fn() }))

beforeEach(() => {
  vi.mocked(fetchAPI).mockReset()
  const responses: Record<string, unknown> = {
    '/settings': [], '/channels': [], '/settings/version': { version: 'test' },
    '/agents/health': null, '/settings/timezone': { execution_timezone: 'Asia/Shanghai' },
    '/providers/services': [
      { id: 1, name: 'First provider', base_url: 'https://example.invalid/v1', models: [
        { id: 11, service_id: 1, name: 'Primary model', model: 'test-model', is_default: true },
      ] },
      { id: 2, name: 'Empty provider', base_url: 'https://example.invalid/v2', models: [] },
    ],
  }
  vi.mocked(fetchAPI).mockImplementation(async path => responses[path] as never)
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true })))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

describe('provider accordion and default model navigation', () => {
  it('expands providers independently and shows empty model lists', async () => {
    render(<SettingsPage />)
    const first = await screen.findByRole('button', { name: '展开 First provider 的模型列表' })
    const second = screen.getByRole('button', { name: '展开 Empty provider 的模型列表' })
    expect(screen.queryByText('Primary model')).toBeNull()
    await userEvent.click(first)
    expect(screen.getByText('Primary model')).toBeTruthy()
    expect(second.getAttribute('aria-expanded')).toBe('false')
    await userEvent.click(second)
    expect(screen.getByText('暂无模型，可添加或嗅探模型')).toBeTruthy()
    await userEvent.click(screen.getByRole('button', { name: '收起 First provider 的模型列表' }))
    expect(screen.queryByText('Primary model')).toBeNull()
    expect(screen.getByRole('button', { name: '收起 Empty provider 的模型列表' })).toBeTruthy()
    expect(vi.mocked(fetchAPI).mock.calls.every(([, options]) => !options?.method)).toBe(true)
  })

  it('opens and focuses the default model after each collapse without changing settings', async () => {
    const scroll = vi.spyOn(HTMLElement.prototype, 'scrollIntoView')
    render(<SettingsPage />)
    const locate = await screen.findByRole('button', { name: '定位默认模型 test-model' })
    for (let attempt = 0; attempt < 2; attempt++) {
      await userEvent.click(locate)
      await waitFor(() => expect(document.activeElement?.id).toBe('ai-model-11'))
      expect(scroll).toHaveBeenLastCalledWith({ behavior: 'instant', block: 'center', inline: 'nearest' })
      await userEvent.click(screen.getByRole('button', { name: '收起 First provider 的模型列表' }))
    }
    expect(vi.mocked(fetchAPI).mock.calls.every(([, options]) => !options?.method)).toBe(true)
  })
})
