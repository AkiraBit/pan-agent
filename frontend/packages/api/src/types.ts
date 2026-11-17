export interface AIModel {
  id: number
  name: string
  service_id: number
  model: string
  is_default: boolean
}

export interface AIService {
  id: number
  name: string
  base_url: string
  api_key: string
  models: AIModel[]
}

export interface NotifyChannel {
  id: number
  name: string
  type: string
  config: Record<string, string>
  enabled: boolean
  is_default: boolean
}

export interface SourceHealth {
  count: number
  success_rate: number | null
  p50_latency_ms: number | null
  last_error?: string
  last_success_at?: number
}

export interface DataSource {
  connection_status?: 'ready' | 'disabled' | 'authorization_required' | null
  id: number
  name: string
  type: string
  type_label?: string
  provider: string
  provider_group?: string
  config: Record<string, unknown>
  enabled: boolean
  priority: number
  supports_batch: boolean
  test_symbols: string[]
  test_settings?: DataSourceTestSettings | null
  engine_attached?: boolean
  business_type?: string | null
  workspace_path?: string | null
  source_probe?: boolean
  ftshare_operation?: import('./ftshare-rest').FtshareOperation | null
  fuyao_operation?: import('./fuyao-rest').FuyaoOperation | null
  routing?: { key: string; mode: 'fallback' | 'aggregate' | 'direct'; label: string; category: string; markets?: string[] }
  health?: SourceHealth | null
  /** 孤儿源:该 (type, provider) 在包内无对应 vendor 且不在种子里,抓取/测试必失败。 */
  is_orphan?: boolean
}

export type DataSourceTestValue = string | number | boolean

export interface DataSourceTestSettings {
  symbols: { markets: string[]; maximum: number; examples: string[]; etf: boolean } | null
  fields: { key: string; type: 'integer' | 'date'; default: DataSourceTestValue | null;
    wire?: string | null; minimum?: number; maximum?: number }[]
  values: Record<string, DataSourceTestValue>
  test_symbols: string[]
}
