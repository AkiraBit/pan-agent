import { fetchAPI } from './client'

export type EmotionPage = 'overview' | 'cycle' | 'playbook' | 'stock' | 'evidence' | 'review' | 'agent' | 'monitor' | 'validation'
export type EmotionStage = 'unknown' | 'startup' | 'expansion' | 'divergence' | 'repair' | 'retreat'
export type Claim = { text: string; evidence_ids: string[] }
export type Evidence = { id: string; kind: string; title: string; source: string; content: unknown; observed_at: string; published_at: string | null; url: string | null; status: string; content_hash: string }
export type EmotionQuote = { symbol: string; name: string; price: number | null; change_pct: number | null; amount_cny: number | null; source: string; source_time: string | null; trade_date: string | null; quality: string }
export type Cycle = { id: string; name: string; stage: EmotionStage; summary: string; symbols: string[]; evidence_ids: string[]; relations: { source: string; target: string; kind: string; explanation: string; evidence_ids: string[] }[] }
export type WatchStock = { symbol: string; role: string; cycle_id: string | null; thesis: string; invalidation: string; evidence_ids: string[] }
export type MetricCheck = { symbol: string; metric: string; operator: string; value: number }
export type VerificationRule = { checks: MetricCheck[]; mode: 'all' | 'any'; persistence_seconds: number; invalidation_checks: MetricCheck[] }
export type Condition = { id: string; title: string; subject: string | null; window: 'premarket' | 'auction' | 'opening' | 'afternoon' | 'close' | 'next_session'; criterion: string; invalidation: string; evidence_ids: string[]; rule?: VerificationRule | null; expression: { symbol: string; metric: string; operator: string; value: number } | null }
export type Scenario = { id: string; title: string; thesis: string; condition_ids: string[]; supports: Claim[]; counters: Claim[]; invalidation: string }
export type EmotionBlock = { id: string; page: EmotionPage; kind: 'verdict' | 'market' | 'cycles' | 'watchlist' | 'scenarios' | 'conditions' | 'evidence' | 'memory' | 'changes' | 'runs' | 'data_quality'; title: string; entity_ids: string[] }
export type Memory = { publication_id: string; revision: number; target_trade_date: string; published_at: string; knowledge_cutoff: string; summary: string; open_questions: string[]; cycles: Cycle[]; symbols: string[] }
export type ContextNote = { id: string; content: string; source_url: string | null; created_at: string; status: 'open' | 'archived'; verification: string }
export type EmotionRun = { id: string; status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'interrupted'; target_trade_date: string; created_at: string; finished_at: string | null; base_revision: number; model_label: string | null; error_code: string | null; publication_id: string | null; events: { seq: number; type: string; at: string; data: Record<string, unknown> }[] }
export type EmotionSettings = { focus_symbols: string[]; schedule_enabled: boolean; schedule_time: string; language: 'zh-CN' | 'en-US'; monitoring_enabled: boolean; monitor_interval_seconds: number; postmarket_enabled: boolean; postmarket_time: string }
export type EmotionPublication = {
  schema_version: string; id: string; revision: number; parent_revision: number; run_id: string; input_version: number; published_at: string; model_label: string;
  target_trade_date: string; knowledge_cutoff: string; market_as_of: string; continuous_monitoring: boolean;
  analysis: { title: string; summary: string; stage: EmotionStage; supports: Claim[]; counters: Claim[]; cycles: Cycle[]; watchlist: WatchStock[]; scenarios: Scenario[]; conditions: Condition[]; memory_summary: string; open_questions: string[]; changes: string[]; blocks: EmotionBlock[] };
  facts: { collected_at: string; reference_trade_date: string; phase: string; coverage: { status: string; count: number; expected: number | null }; quotes: EmotionQuote[]; evidence: Evidence[]; capabilities: Record<string, boolean>; snapshot: { market: { rising: number; falling: number; valid: number; median: number | null }; sentiment: { counts: Record<string, number | null>; break_rate: number | null; yesterday_mean: number | null } } };
  context: ContextNote[]; memory_input: Memory[]; review_memory_input?: ReviewMemory[];
  condition_states: { id: string; state: 'waiting' | 'unknown' | 'review_required' | 'met' | 'not_met'; reason: string; observed_value: number | null; observed_at: string }[];
}
export type EmotionWorkspace = { publication: EmotionPublication | null; settings: EmotionSettings; validation_trade_date?: string | null; target_trade_date: string | null; server_time: string; input_version: number; history: { id: string; revision: number; target_trade_date: string; published_at: string; title: string }[]; runs: EmotionRun[]; notes: ContextNote[] }
export type AuctionSource = { enabled: boolean; endpoint: string; provider_name: string; has_api_key: boolean }
export type ObservationState = { id: string; state: 'waiting' | 'unknown' | 'review_required' | 'met' | 'not_met' | 'observing' | 'invalidated'; reason: string; observed_at: string; last_source_time: string | null; since: string | null; checks: Array<MetricCheck & { observed_value: number | null; source_time: string | null; passed: boolean | null; error: string | null }> }
export type Observation = { id: string; observed_at: string; phase: string; quotes: EmotionQuote[]; auction: { status: string; provider: string; quotes: Array<{ symbol: string; source_time: string; reference_price: number; matched_volume_shares: number; unmatched_volume_shares: number; unmatched_side: string; final: boolean }> }; evaluations: ObservationState[] }
export type ReviewMemory = { review_id: string; target_trade_date: string; memory_summary: string; next_day_focus: string[]; open_questions: string[] }
export type EmotionReview = { id: string; published_at: string; model_label: string; analysis: { title: string; summary: string; findings: Array<{ condition_id: string; assessment: 'supported' | 'contradicted' | 'inconclusive'; explanation: string; evidence_ids: string[] }>; lessons: string[]; next_day_focus: string[]; memory_summary: string; open_questions: string[] }; summary: { sample_count: number; has_closing_sample: boolean; prospective_plan: boolean }; evidence: Evidence[] }
export type Lifecycle = { monitor: { id: string; status: string; last_sample_at: string | null; last_error: string | null } | null; sample_count: number; latest: Observation | null; timeline: Array<{ id: string; observed_at: string; phase: string; states: Record<string, string> }>; review: EmotionReview | null; auction_source: AuctionSource }
export type SessionValidation = {
  trade_date: string; next_trade_date: string | null; enabled: boolean; server_time: string; heartbeat_at: string | null; status: string; warnings: string[];
  checkpoints: Array<{ id: string; status: string; reason: string; samples?: number; expected?: number; coverage?: number; max_gap_seconds?: number; start?: string; end?: string }>;
  events: Array<{ at: string; type: string; states?: Record<string, string> }>;
}
export const emotionApi = {
  overview: (signal?: AbortSignal) => fetchAPI<SentimentOverviewState>('/short-term/sentiment-overview', { signal }),
  refreshOverview: (body: { request_key: string; language: 'zh-CN' | 'en-US'; force: boolean }) => fetchAPI<{ run: EmotionRun | null; started: boolean }>('/short-term/sentiment-overview/refresh', { method: 'POST', body: JSON.stringify(body) }),
  sessionValidation: (day: string, signal?: AbortSignal) => fetchAPI<SessionValidation>(`/short-term/session-validation/${encodeURIComponent(day)}`, { signal }),
  armSessionValidation: (day: string, enabled: boolean) => fetchAPI<SessionValidation>(`/short-term/session-validation/${encodeURIComponent(day)}`, { method: 'PUT', body: JSON.stringify({ enabled }) }),
  lifecycle: (id: string, signal?: AbortSignal) => fetchAPI<Lifecycle>(`/short-term/publications/${encodeURIComponent(id)}/lifecycle`, { signal }),
  monitor: (id: string, enabled: boolean) => fetchAPI<Lifecycle>(`/short-term/publications/${encodeURIComponent(id)}/monitor`, { method: 'POST', body: JSON.stringify({ enabled }) }),
  review: (publication_id: string, request_key: string) => fetchAPI<EmotionRun>('/short-term/reviews', { method: 'POST', body: JSON.stringify({ publication_id, request_key }) }),
  auctionSource: () => fetchAPI<AuctionSource>('/short-term/auction-source'),
  saveAuctionSource: (body: { enabled: boolean; endpoint: string; provider_name: string; api_key?: string; clear_api_key?: boolean }) => fetchAPI<AuctionSource>('/short-term/auction-source', { method: 'PUT', body: JSON.stringify(body) }),
  workspace: (signal?: AbortSignal) => fetchAPI<EmotionWorkspace>('/short-term/workspace', { signal }),
  publication: (id: string, signal?: AbortSignal) => fetchAPI<EmotionPublication>(`/short-term/publications/${encodeURIComponent(id)}`, { signal }),
  run: (body: { request_key: string; language: string; target_trade_date?: string }) => fetchAPI<EmotionRun>('/short-term/runs', { method: 'POST', body: JSON.stringify(body) }),
  cancel: (id: string) => fetchAPI(`/short-term/runs/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  settings: (body: EmotionSettings) => fetchAPI<EmotionSettings>('/short-term/workspace/settings', { method: 'PUT', body: JSON.stringify(body) }),
  context: (content: string, source_url: string | null) => fetchAPI<ContextNote>('/short-term/context-notes', { method: 'POST', body: JSON.stringify({ content, source_url }) }),
  contextStatus: (id: string, status: 'open' | 'archived') => fetchAPI<ContextNote>(`/short-term/context-notes/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify({ status }) }),
}

export type SentimentStage = 'ice' | 'repair' | 'expansion' | 'heat' | 'divergence' | 'retreat'
export type SentimentDirection = 'improving' | 'stable' | 'deteriorating' | 'mixed' | 'insufficient'
export type StagePosition = { kind: 'stage' | 'between' | 'unknown'; stages: SentimentStage[]; status: 'candidate' | 'supported' | 'conflicted' | 'insufficient'; rationale: string; evidence_ids: string[] }
export type SentimentAxis = { state: SentimentDirection; explanation: string; evidence_ids: string[] }
export type Breadth = { valid: number; rising: number; falling: number; flat: number; positive_ratio: number | null; median: number | null; p10: number | null; p90: number | null }
export type SentimentOverview = {
  schema_version: string; run_id: string; input_version: number; trade_date: string; previous_trade_date: string | null;
  as_of: string; collected_at: string; analyzed_at: string; refresh_after: string; intraday: boolean; provider: string; model_label: string;
  skill: { id: string; version: string };
  coverage: { status: 'complete' | 'partial'; directory_total: number; directory_count: number; valid: number; excluded_st: number; excluded_halted: number; excluded_unsupported?: number; missing_or_stale: number; directory_missing: number };
  metrics: { breadth: Breadth; boards: Array<Breadth & { board: 'main' | 'growth' | 'star' | 'beijing'; directory_count: number; strong_count: number | null; weak_count: number | null; threshold_pct: number }>; feedback: { status: string; valid: number; cohort_count: number; mean_change_pct: number | null } };
  indices: Array<{ symbol: string; price: number; change_pct: number; source_time: string }>;
  temperature: { temperature?: number; quality: string; timestamp?: string };
  evidence: Evidence[];
  analysis: { title: string; summary: string; direction: SentimentDirection; direction_reason: string; stage: StagePosition; loss_relief: SentimentAxis; profit_diffusion: SentimentAxis;
    groups: Array<{ group: 'G' | 'A' | 'P' | 'R'; status: 'observed' | 'proxy' | 'missing' | 'conflicted'; explanation: string; evidence_ids: string[] }>;
    supports: Claim[]; counters: Claim[]; next_checks: Array<{ window: string; observe: string; strengthens: string; invalidates: string }>; limitations: string[] };
}
export type SentimentOverviewState = { overview: SentimentOverview | null; stale: boolean; active_run: EmotionRun | null; last_run: EmotionRun | null; can_analyze: boolean; skill_enabled: boolean; connection_status: string; retry_after: string | null; server_time: string }
