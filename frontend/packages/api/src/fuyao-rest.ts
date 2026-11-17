import { fetchAPI } from './client'

export type FuyaoGroup = 'a-share' | 'a-share-index' | 'fund' | 'futures' | 'options' | 'hk-share' | 'meta' | 'news'

export interface FuyaoParameter {
  name: string
  type: 'string' | 'integer' | 'number' | 'boolean'
  description: string
  required: boolean
  example?: string | number | boolean
  default?: string | number | boolean
  enum?: string[]
  minimum?: number
  maximum?: number
  encoding?: 'date-ms'
  example_days_ago?: number
}

export interface FuyaoOperation {
  id: string
  method: 'GET'
  path: string
  group: FuyaoGroup
  summary: string
  description: string
  docs_url: string
  parameters: FuyaoParameter[]
}

export interface FuyaoCatalog {
  configured: boolean
  paused: boolean
  source: string
  version: string
  operations: (FuyaoOperation & { enabled: boolean; settings?: { params?: Record<string, string> } | null })[]
}

export interface FuyaoQueryResult {
  http_status: number
  business_code: number | null
  request_id: string | null
  response_json: string | null
}

const BASE = '/datasources/fuyao'

export function getFuyaoCatalog(signal?: AbortSignal) {
  return fetchAPI<FuyaoCatalog>(`${BASE}/catalog`, { signal })
}

export function queryFuyao(operation: string, params: Record<string, string>, signal?: AbortSignal) {
  return fetchAPI<FuyaoQueryResult>(`${BASE}/query/${encodeURIComponent(operation)}`, {
    method: 'POST', body: JSON.stringify({ params }), signal, timeoutMs: 30_000,
  })
}
