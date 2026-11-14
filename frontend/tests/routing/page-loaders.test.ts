import { describe, expect, it } from 'vitest'

import { pageLoaders, resolveRouteKey } from '@/router/page-loaders'

describe('route page loaders', () => {
  it('registers every route page exactly once', () => {
    expect(Object.keys(pageLoaders)).toEqual([
      'login',
      'dashboard',
      'workspace',
      'gettingStarted',
      'stocks',
      'shortTerm',
      'opportunities',
      'paperTrading',
      'assistant',
      'alerts',
      'agents',
      'evaluations',
      'history',
      'dataSources',
      'settings',
      'analysisDetail',
    ])
  })

  it('resolves both assistant routes to the same page loader', () => {
    expect(resolveRouteKey('/assistant')).toBe('assistant')
    expect(resolveRouteKey('/assistant/123')).toBe('assistant')
  })

  it('keeps the original dashboard separate from market panels', () => {
    expect(resolveRouteKey('/')).toBe('dashboard')
    expect(resolveRouteKey('/limit-up')).toBe('dashboard')
    expect(resolveRouteKey('/workspace')).toBe('workspace')
  })

  it('resolves the short-term guide', () => {
    expect(resolveRouteKey('/short-term')).toBe('shortTerm')
  })

  it('does not preload an unknown route', () => {
    expect(resolveRouteKey('/missing')).toBeNull()
  })

  it('resolves the recoverable setup page', () => {
    expect(resolveRouteKey('/getting-started')).toBe('gettingStarted')
  })
})
