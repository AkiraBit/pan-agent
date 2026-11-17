import { fetchAPI } from './client'

export type FtshareTier = 'free' | 'basic'

export interface FtshareParameter {
  name: string
  type: 'string' | 'integer' | 'number' | 'boolean'
  required: boolean
  description: string
  enum?: string[]
  default?: string
  format?: 'YYYYMMDD' | 'YYYY-MM-DD'
  minimum?: number
  maximum?: number
}

export interface FtshareSettings {
  variant: number
  params: Record<string, string>
}

export interface FtshareVariant {
  path: string
  parameters: FtshareParameter[]
  preset: Record<string, string>
  rules: { kind: 'exactly_one' | 'at_least_one' | 'together' | 'exclusive' | 'unless' | 'same'; fields: string[] }[]
}

export interface FtshareOperation {
  id: string
  summary: string
  method: 'GET'
  docs_url: string
  tier: FtshareTier
  group: string
  subgroup?: string
  variants: FtshareVariant[]
}

export interface FtshareCatalog {
  configured: boolean
  paused: boolean
  source: string
  operations: (FtshareOperation & { enabled: boolean; settings: FtshareSettings | null })[]
}

export interface FtshareResult {
  http_status: number
  business_code: number | null
  response_json: string | null
  message: string | null
}

const path = '/datasources/ftshare'
export const getFtshareCatalog = (signal?: AbortSignal) => fetchAPI<FtshareCatalog>(path + '/catalog', { signal })
export const queryFtshare = (operation: string, settings: FtshareSettings, signal?: AbortSignal) =>
  fetchAPI<FtshareResult>(path + '/query/' + encodeURIComponent(operation), {
    method: 'POST', body: JSON.stringify(settings), timeoutMs: 30_000, signal,
  })
