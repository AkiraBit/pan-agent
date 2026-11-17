import { useConfirm } from '@panwatch/base-ui/components/ui/confirm-dialog'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Pencil, Database, Newspaper, LineChart, TrendingUp, DollarSign, Image, Layers, Zap, Check, X, Clock, Trash2, RotateCcw, AlertTriangle, BarChart3, Trophy, Landmark, Users, Gift, ArrowLeftRight, ListOrdered, KeyRound, BookOpen, ChevronDown, Power, PowerOff } from 'lucide-react'
import { fetchAPI, resetDataSourcesToSeed, type DataSource, type DataSourceTestSettings, type DataSourceTestValue, type FtshareOperation, type FtshareSettings, type FtshareTier, type FuyaoOperation, type TushareOperation } from '@panwatch/api'
import { Input } from '@panwatch/base-ui/components/ui/input'
import { Label } from '@panwatch/base-ui/components/ui/label'
import { Button } from '@panwatch/base-ui/components/ui/button'
import { Switch } from '@panwatch/base-ui/components/ui/switch'
import { Badge } from '@panwatch/base-ui/components/ui/badge'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@panwatch/base-ui/components/ui/dialog'
import { Popover, PopoverContent, PopoverTrigger } from '@panwatch/base-ui/components/ui/popover'
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from '@panwatch/base-ui/components/ui/select'
import { useToast } from '@panwatch/base-ui/components/ui/toast'
import { useTranslation } from 'react-i18next'
import { formatNumber } from '@/i18n/format'
import { marketSignTextClass } from '@/lib/market-colors'
import { FtshareParameters, FtshareTierBadge, ftshareQueryValues, initialFtshareSettings } from '@/components/FtshareParameters'
import { FuyaoParameters, fuyaoQueryValues, initialFuyaoParams } from '@/components/FuyaoParameters'
import { SourceTestParameters } from '@/components/SourceTestParameters'
import { FtshareResponse } from '@/components/FtshareResponse'
import { ALL_FTSHARE_CATEGORIES, FtshareCategoryFilters, matchesFtshareCategory } from '@/components/FtshareCategoryFilters'
import { DataSourcesGlobalSearch, EndpointSearchInput, type EndpointSearchEntry } from '@/components/DataSourceSearch'
import { endpointSearchTokens, ftshareSearchFields, matchesEndpointSearch, normalizeEndpointTerm } from '@/lib/data-source-search'

interface TestLogItem {
  timestamp: string
  source_name: string
  source_type: string
  action: 'start' | 'success' | 'error'
  message: string
  duration_ms: number
  count: number
}

export interface TestErrorItem {
  symbol: string
  market?: string
  error: string
}

export function TestErrorList({ errors }: { errors: TestErrorItem[] }) {
  const { t } = useTranslation('configuration')
  if (errors.length === 0) return null

  return (
    <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/20">
      <div className="text-[11px] text-amber-600 dark:text-amber-400 font-medium mb-1">{t('dataSources.result.missingDetails')}</div>
      <div className="space-y-1">
        {errors.map((item, i) => (
          <div key={`${item.symbol}-${i}`} className="text-[12px] text-amber-700 dark:text-amber-300">
            {item.symbol}{item.market ? ` (${item.market})` : ''}: {item.error}
          </div>
        ))}
      </div>
    </div>
  )
}

interface TestResult {
  test_passed: boolean
  source_name: string
  source_type: string
  type_label: string
  provider: string
  supports_batch: boolean
  test_symbols: string[]
  test_params?: Record<string, DataSourceTestValue | null>
  count: number
  duration_ms: number
  error?: string
  raw_response?: string | null
  http_status?: number
  business_code?: number | null
  ftshare_tier?: FtshareTier
  errors?: TestErrorItem[]
  items?: unknown[] | { image?: string }  // array for most types, object for chart
  logs: TestLogItem[]
}

interface DataSourceForm {
  name: string
  type: string
  provider: string
  providerGroup?: string
  config: Record<string, unknown>
  ftshareOperation?: FtshareOperation | null
  fuyaoOperation?: FuyaoOperation | null
  tushareOperation?: TushareOperation | null
  testSettings?: DataSourceTestSettings | null
}

const DATASOURCE_TYPES = {
  etf_nav: { icon: DollarSign, color: 'text-indigo-500' },
  etf_turnover: { icon: BarChart3, color: 'text-indigo-500' },
  news: { icon: Newspaper, color: 'text-blue-500' },
  kline: { icon: LineChart, color: 'text-orange-500' },
  capital_flow: { icon: DollarSign, color: 'text-yellow-500' },
  quote: { icon: TrendingUp, color: 'text-emerald-500' },
  events: { icon: Layers, color: 'text-violet-500' },
  chart: { icon: Image, color: 'text-purple-500' },
  flash_news: { icon: Zap, color: 'text-amber-500' },
  fundamentals: { icon: BarChart3, color: 'text-indigo-500' },
  dragon_tiger: { icon: Trophy, color: 'text-red-500' },
  margin: { icon: Landmark, color: 'text-cyan-500' },
  shareholders: { icon: Users, color: 'text-teal-500' },
  dividend: { icon: Gift, color: 'text-pink-500' },
  northbound: { icon: ArrowLeftRight, color: 'text-sky-500' },
  stock_search: { icon: Database, color: 'text-blue-500' },
  trading_calendar: { icon: Clock, color: 'text-violet-500' },
  index_quote: { icon: TrendingUp, color: 'text-emerald-500' },
  index_kline: { icon: LineChart, color: 'text-orange-500' },
  index_constituents: { icon: Layers, color: 'text-indigo-500' },
  market_sentiment: { icon: Zap, color: 'text-amber-500' },
  auction: { icon: BarChart3, color: 'text-sky-500' },
  ipo: { icon: Landmark, color: 'text-sky-500' },
  etf_adjusted_history: { icon: LineChart, color: 'text-orange-500' },
  fund_holdings: { icon: Layers, color: 'text-violet-500' },
  fund_research: { icon: Database, color: 'text-violet-500' },
  fund_backtest: { icon: LineChart, color: 'text-violet-500' },
  futures_research: { icon: BarChart3, color: 'text-orange-500' },
  options_research: { icon: Layers, color: 'text-orange-500' },
}

// 数据源分类分组:仅用于页面展示时的二级归组,不影响数据结构与后端
const DATASOURCE_CATEGORIES: { key: string; types: string[] }[] = [
  { key: 'quote_kline', types: ['quote', 'kline', 'index_quote', 'index_kline', 'index_constituents', 'stock_search', 'trading_calendar'] },
  { key: 'etf', types: ['etf_nav', 'etf_adjusted_history', 'etf_turnover'] },
  { key: 'news', types: ['news', 'flash_news', 'events'] },
  { key: 'fundamentals', types: ['fundamentals'] },
  { key: 'capital', types: ['capital_flow', 'dragon_tiger', 'market_sentiment', 'auction', 'margin', 'shareholders', 'northbound', 'dividend', 'ipo'] },
  { key: 'research', types: ['fund_research', 'fund_holdings', 'fund_backtest', 'futures_research', 'options_research'] },
  { key: 'chart', types: ['chart'] },
]

const CATEGORY_BY_TYPE = new Map(DATASOURCE_CATEGORIES.flatMap(category => category.types.map(type => [type, category.key] as const)))
const categoryOf = (type: string) => CATEGORY_BY_TYPE.get(type) ?? 'other'
const PROVIDERS = ['fuyao', 'ftshare', 'tushare', 'cls', 'eastmoney', 'tencent', 'sina'] as const
type ProviderId = typeof PROVIDERS[number]
const isProvider = (id: string): id is ProviderId => (PROVIDERS as readonly string[]).includes(id)
const providerOf = (source: DataSource) => source.provider_group ?? source.provider
const needsProviderConnection = (source: DataSource) =>
  (source.provider === 'fuyao' || source.provider === 'ftshare' || source.provider === 'tushare') && source.connection_status !== 'ready'
const TYPE_ORDER = [...CATEGORY_BY_TYPE.keys()]
const typeOrder = (type: string) => {
  const index = TYPE_ORDER.indexOf(type)
  return index === -1 ? TYPE_ORDER.length : index
}

const emptyForm: DataSourceForm = { name: '', type: '', provider: '', config: {} }

function EndpointPowerMenu({ allOn, allOff, disabled, busy, canEnable, onChange }: {
  allOn: boolean; allOff: boolean; disabled: boolean; busy: boolean; canEnable: boolean
  onChange: (enabled: boolean) => void
}) {
  const { t } = useTranslation('configuration')
  const [open, setOpen] = useState(false)
  const label = t('dataSources.bulkActivation.label')
  return <Popover open={open} onOpenChange={next => { if (!next || (!disabled && !busy)) setOpen(next) }}>
    <PopoverTrigger asChild>
      <Button type="button" size="sm" variant="outline" className="h-8 shrink-0 gap-1 px-2 text-muted-foreground aria-expanded:bg-muted aria-expanded:text-foreground"
        aria-label={label} title={label} aria-busy={busy} aria-disabled={busy || undefined} disabled={disabled}>
        <Power className="size-3.5" aria-hidden="true" />
        <ChevronDown className="size-3" aria-hidden="true" />
      </Button>
    </PopoverTrigger>
    <PopoverContent align="end" sideOffset={6} aria-label={label} className="w-36 space-y-0.5 p-1">
      {([true, false] as const).map(enabled => {
        const selected = enabled ? allOn : allOff
        const Icon = enabled ? Power : PowerOff
        return <Button key={String(enabled)} type="button" variant="ghost" size="sm" className="w-full justify-start gap-2 px-2.5"
          disabled={selected || disabled || busy || (enabled && !canEnable)} aria-current={selected || undefined}
          onClick={() => { setOpen(false); onChange(enabled) }}>
          <Icon className="size-3.5" aria-hidden="true" />
          {t(enabled ? 'dataSources.bulkActivation.on' : 'dataSources.bulkActivation.off')}
          {selected && <Check className="ml-auto size-3.5" aria-hidden="true" />}
        </Button>
      })}
    </PopoverContent>
  </Popover>
}

export default function DataSourcesPage() {
  const { t } = useTranslation(['configuration', 'common'])
  const confirmAction = useConfirm()
  const configT = t as unknown as (key: string, options?: Record<string, unknown>) => string
  const [sources, setSources] = useState<DataSource[]>([])
  const [pausedProviders, setPausedProviders] = useState<Set<string>>(() => new Set())
  const [providerSaving, setProviderSaving] = useState(false)
  const [bulkSaving, setBulkSaving] = useState(false)
  const [loading, setLoading] = useState(true)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [form, setForm] = useState<DataSourceForm>(emptyForm)
  const [editId, setEditId] = useState<number | null>(null)
  const [testing, setTesting] = useState<number | null>(null)
  const [testResult, setTestResult] = useState<TestResult | null>(null)
  const [testResultOpen, setTestResultOpen] = useState(false)
  const [testSymbolsInput, setTestSymbolsInput] = useState('')
  const [probeParams, setProbeParams] = useState<Record<string, DataSourceTestValue>>({})
  const [resetting, setResetting] = useState(false)
  const [selectedProvider, setSelectedProvider] = useState<ProviderId | null>(null)
  const [category, setCategory] = useState('all')
  const [ftshareConfigured, setFtshareConfigured] = useState<boolean | null>(null)
  const [ftshareTier, setFtshareTier] = useState<FtshareTier | 'all'>('all')
  const [ftshareCategory, setFtshareCategory] = useState(ALL_FTSHARE_CATEGORIES)
  const [scopedSearch, setScopedSearch] = useState('')
  const [locatedSource, setLocatedSource] = useState<{ id: number } | null>(null)
  const endpointList = useRef<HTMLDivElement>(null)
  const [ftshareSettings, setFtshareSettings] = useState<FtshareSettings>({ variant: 0, params: {} })
  const [catalogParams, setCatalogParams] = useState<Record<string, string>>({})
  const catalogOperation = form.fuyaoOperation ?? form.tushareOperation
  const [tushareFields, setTushareFields] = useState('')
  const [orderOpen, setOrderOpen] = useState(false)
  const [orderType, setOrderType] = useState('quote')
  const [orderSearch, setOrderSearch] = useState('')
  const [toggling, setToggling] = useState<number | null>(null)
  const [testStatuses, setTestStatuses] = useState<Record<number, 'passed' | 'failed'>>({})
  const [loadFailed, setLoadFailed] = useState(false)
  const { toast } = useToast()

  const load = async (readProviderStatus = false) => {
    try {
      const [rows, activation] = await Promise.all([
        fetchAPI<DataSource[]>('/datasources'),
        readProviderStatus ? fetchAPI<{ paused: string[] }>('/datasources/providers') : Promise.resolve(null),
      ])
      setSources(rows)
      if (activation) setPausedProviders(new Set(activation.paused))
      setLoadFailed(false)
    } catch {
      setLoadFailed(true)
      toast(t('configuration:dataSources.messages.loadFailed'), 'error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load(true) }, [])

  useEffect(() => {
    if (selectedProvider !== 'ftshare') return
    const controller = new AbortController()
    fetchAPI<{ configured: boolean }>('/settings/data-providers/ftshare', { signal: controller.signal })
      .then(result => { if (!controller.signal.aborted) setFtshareConfigured(result.configured) })
      .catch(() => { if (!controller.signal.aborted) setFtshareConfigured(null) })
    return () => controller.abort()
  }, [selectedProvider])

  const providerName = (id: string) => configT(`dataSources.providers.${id}`, { defaultValue: id })
  const typeName = (id: string) => configT(`dataSources.types.${id}`, { defaultValue: id })
  const categoryName = (id: string) => configT(`dataSources.categories.${id}`, { defaultValue: id })
  const searchEntries = useMemo(() => sources.flatMap((source): EndpointSearchEntry[] => {
    const providerId = providerOf(source)
    if (!isProvider(providerId)) return []
    const provider = configT(`dataSources.providers.${providerId}`, { defaultValue: providerId })
    const operation = source.ftshare_operation
    const fuyao = source.fuyao_operation
    const tushare = source.tushare_operation
    const category = operation ?? tushare
    const detail = category ? [category.group, category.subgroup].filter(Boolean).join(' · ')
      : configT(`dataSources.types.${source.business_type ?? source.type}`, { defaultValue: source.type_label || source.type })
    const labels = [
      source.name, provider, providerId, source.provider, source.type, detail,
      ...(operation ? [...ftshareSearchFields(operation), operation.tier, configT(`ftshare.tiers.${operation.tier}`)] : []),
      ...(fuyao ? [fuyao.group, fuyao.path, fuyao.description, ...fuyao.parameters.map(param => param.name)] : []),
      ...(tushare ? [tushare.id, ...tushare.parameters.map(param => param.name)] : []),
    ]
    return [{ id: source.id, name: source.name, provider, detail,
      tier: operation?.tier, path: operation?.variants[0]?.path ?? fuyao?.path, operationId: operation?.id ?? fuyao?.id ?? tushare?.id,
      index: labels.map(normalizeEndpointTerm) }]
  }), [sources, configT])
  const searchById = useMemo(() => new Map(searchEntries.map(entry => [entry.id, entry.index])), [searchEntries])
  const byProvider = new Map<string, DataSource[]>()
  const byRouting = new Map<string, { mode: 'fallback' | 'aggregate' | 'direct'; label: string; rows: DataSource[] }>()
  for (const source of sources) {
    const provider = providerOf(source)
    if (!isProvider(provider)) continue
    if (!byProvider.has(provider)) byProvider.set(provider, [])
    byProvider.get(provider)!.push(source)
    const route = source.routing
    const key = route?.key ?? source.type
    const mode = route?.mode ?? 'direct'
    const groupId = `${mode}:${key}`
    if (!byRouting.has(groupId)) byRouting.set(groupId, {
      mode,
      label: mode === 'fallback' && key === 'kline' ? t('configuration:dataSources.callOrder.dailyKline')
        : key.startsWith('rest:') ? route?.label ?? key : typeName(key),
      rows: [],
    })
    byRouting.get(groupId)!.rows.push(source)
  }
  const activeProvider = selectedProvider ?? PROVIDERS.find(id => byProvider.has(id)) ?? 'fuyao'
  const providerSources = byProvider.get(activeProvider) ?? []
  const sortEndpoints = (a: DataSource, b: DataSource) => activeProvider === 'tushare'
    ? (a.tushare_operation?.order ?? Infinity) - (b.tushare_operation?.order ?? Infinity) || a.id - b.id
    : typeOrder(a.business_type ?? a.type) - typeOrder(b.business_type ?? b.type) || a.id - b.id
  const providerPaused = pausedProviders.has(activeProvider)
  const countedEndpoints = activeProvider === 'fuyao' ? providerSources.filter(source => source.fuyao_operation) : providerSources
  const bulkEndpoints = countedEndpoints.filter(source => !source.is_orphan)
  const showBulkControls = bulkEndpoints.length > 1
  const allEndpointsOn = bulkEndpoints.every(source => source.enabled)
  const allEndpointsOff = bulkEndpoints.every(source => !source.enabled)
  const restProvider = activeProvider === 'ftshare' || activeProvider === 'fuyao' || activeProvider === 'tushare'
  const restCategory = (source: DataSource) => source.ftshare_operation ?? source.tushare_operation ?? (source.fuyao_operation
    ? { group: source.fuyao_operation.group, subgroup: source.business_type ?? undefined }
    : { group: 'other' })
  const presentCategories = new Set(providerSources.map(source => categoryOf(source.type)))
  const categories = ['all', ...DATASOURCE_CATEGORIES.map(group => group.key), 'other']
    .filter(key => key === 'all' || presentCategories.has(key))
  const activeCategory = categories.includes(category) ? category : 'all'
  const restOperations = restProvider ? [...providerSources].sort(sortEndpoints).map(restCategory) : []
  const hasSourceSearch = providerSources.length > 1
  const showCategoryBar = restProvider ? hasSourceSearch : categories.length > 2
  const scopedTokens = endpointSearchTokens(scopedSearch)
  const visibleSources = providerSources
    .filter(source => restProvider
      ? matchesFtshareCategory(restCategory(source), ftshareCategory)
        && (activeProvider !== 'ftshare' || ftshareTier === 'all' || source.ftshare_operation?.tier === ftshareTier)
      : activeCategory === 'all' || categoryOf(source.type) === activeCategory)
    .filter(source => !scopedTokens.length || matchesEndpointSearch(searchById.get(source.id) ?? [], scopedTokens))
    .sort(sortEndpoints)
  const orderTokens = endpointSearchTokens(orderSearch)
  const orderTypes = [...byRouting.keys()].filter(key => {
    if (!orderTokens.length) return true
    const group = byRouting.get(key)!
    const label = normalizeEndpointTerm(group.label)
    return group.rows.some(row => matchesEndpointSearch([label, ...(searchById.get(row.id) ?? [])], orderTokens))
  }).sort((a, b) => {
    const rank = (key: string) => {
      const group = byRouting.get(key)!
      return group.mode === 'fallback' ? (group.rows.length > 1 ? 0 : 1) : group.mode === 'aggregate' ? 2 : 3
    }
    return rank(a) - rank(b) || typeOrder(a.slice(a.indexOf(':') + 1)) - typeOrder(b.slice(b.indexOf(':') + 1))
      || byRouting.get(a)!.label.localeCompare(byRouting.get(b)!.label)
  })
  const activeOrderType = orderTypes.includes(orderType) ? orderType : orderTypes[0]
  const orderGroup = byRouting.get(activeOrderType)
  const orderRows = [...(orderGroup?.rows ?? [])]
    .filter(row => orderGroup?.mode !== 'direct' || !orderTokens.length
      || matchesEndpointSearch([normalizeEndpointTerm(orderGroup.label), ...(searchById.get(row.id) ?? [])], orderTokens))
    .sort((a, b) => orderGroup?.mode === 'fallback'
      ? Number(providerOf(b) === 'ftshare') - Number(providerOf(a) === 'ftshare') || a.id - b.id
      : a.id - b.id)
  const orderStatus = (source: DataSource) => pausedProviders.has(providerOf(source)) ? 'providerPaused'
    : !source.enabled ? 'disabled' : needsProviderConnection(source) ? 'authorization'
    : source.is_orphan ? 'unavailable' : 'enabled'

  const credentialConfigured = activeProvider === 'ftshare'
    ? ftshareConfigured ?? (providerSources.length ? providerSources.some(source => source.connection_status === 'ready') : null)
    : restProvider && providerSources.some(source => source.provider === activeProvider)
      ? providerSources.some(source => source.provider === activeProvider && source.connection_status === 'ready') : null

  function selectProvider(id: ProviderId) {
    setSelectedProvider(id)
    setCategory('all')
    setFtshareTier('all')
    setFtshareCategory(ALL_FTSHARE_CATEGORIES)
    setScopedSearch('')
    setLocatedSource(null)
  }

  function revealSource(id: number) {
    const source = sources.find(row => row.id === id)
    if (!source) return
    const provider = providerOf(source)
    if (!isProvider(provider)) return
    selectProvider(provider)
    setLocatedSource({ id })
  }

  useLayoutEffect(() => {
    const list = endpointList.current
    if (!list || !locatedSource) return
    const row = list.querySelector<HTMLElement>(`[data-source-id="${locatedSource.id}"]`)
    if (!row) return
    const headerHeight = list.querySelector('thead')?.offsetHeight ?? 0
    list.scrollTop = Math.max(0, list.scrollTop + row.getBoundingClientRect().top - list.getBoundingClientRect().top - headerHeight)
    const bounds = row.getBoundingClientRect()
    if (window.innerWidth < 768 && (bounds.top < 70 || bounds.bottom > window.innerHeight - 56)) {
      row.scrollIntoView({ block: 'center' })
    }
    row.focus({ preventScroll: true })
  }, [locatedSource])

  const openDialog = (source: DataSource) => {
    setForm({ name: source.name, type: source.type, provider: source.provider,
      providerGroup: providerOf(source), config: source.config || {}, ftshareOperation: source.ftshare_operation,
      fuyaoOperation: source.fuyao_operation, tushareOperation: source.tushare_operation, testSettings: source.test_settings })
    if (source.ftshare_operation) setFtshareSettings(initialFtshareSettings(source.ftshare_operation, source.config))
    const operation = source.fuyao_operation ?? source.tushare_operation
    if (operation) setCatalogParams(initialFuyaoParams(operation, source.config))
    if (source.tushare_operation) {
      setTushareFields(typeof source.config?.fields === 'string' ? source.config.fields : '')
    }
    setTestSymbolsInput((source.test_settings?.test_symbols ?? source.test_symbols ?? []).join(', '))
    setProbeParams(source.test_settings?.values ?? {})
    setEditId(source.id)
    setDialogOpen(true)
  }

  const saveSource = async () => {
    if (editId === null) return
    const testSymbols = testSymbolsInput.split(/[,，\s]+/).filter(Boolean)
    try {
      await fetchAPI(`/datasources/${editId}`, { method: 'PUT',
        body: JSON.stringify(form.ftshareOperation ? { config: ftshareQueryValues(ftshareSettings) }
          : catalogOperation ? { config: {
            params: fuyaoQueryValues(catalogParams), ...(form.tushareOperation && { fields: tushareFields }),
          } }
            : form.testSettings ? { test_params: probeParams, ...(form.testSettings.symbols && { test_symbols: testSymbols }) }
              : { test_symbols: testSymbols, config: form.config }) })
      setTestStatuses(({ [editId]: _previous, ...rest }) => rest)
      setDialogOpen(false)
      void load()
      toast(t('configuration:dataSources.messages.saved'), 'success')
    } catch (e) { toast(e instanceof Error ? e.message : t('configuration:dataSources.messages.saveFailed'), 'error') }
  }

  const toggleEnabled = async (source: DataSource) => {
    if (toggling !== null || providerSaving || bulkSaving || providerPaused) return
    setToggling(source.id)
    try {
      await fetchAPI(`/datasources/${source.id}`, {
        method: 'PUT', body: JSON.stringify({ enabled: !source.enabled }),
      })
      setSources(previous => previous.map(row => row.id === source.id ? { ...row, enabled: !source.enabled } : row))
    } catch {
      toast(t('configuration:dataSources.messages.operationFailed'), 'error')
    } finally { setToggling(null) }
  }

  const toggleAllEndpoints = async (enabled: boolean) => {
    if (bulkSaving || providerPaused || providerSaving || toggling !== null || testing !== null || resetting) return
    setBulkSaving(true)
    try {
      const result = await fetchAPI<{ enabled: boolean; source_ids: number[] }>(
        `/datasources/providers/${encodeURIComponent(activeProvider)}/endpoints`, {
          method: 'PUT', body: JSON.stringify({ enabled }),
        },
      )
      const ids = new Set(result.source_ids)
      setSources(previous => previous.map(row => ids.has(row.id) ? { ...row, enabled: result.enabled } : row))
    } catch (e) {
      toast(e instanceof Error ? e.message : t('configuration:dataSources.messages.operationFailed'), 'error')
    } finally { setBulkSaving(false) }
  }

  const toggleProvider = async (provider: ProviderId, enabled: boolean) => {
    if (providerSaving || bulkSaving || toggling !== null || testing !== null || resetting) return
    setProviderSaving(true)
    try {
      await fetchAPI(`/datasources/providers/${encodeURIComponent(provider)}`, {
        method: 'PUT', body: JSON.stringify({ enabled }),
      })
      setPausedProviders(previous => {
        const next = new Set(previous)
        if (enabled) next.delete(provider)
        else next.add(provider)
        return next
      })
    } catch {
      toast(t('configuration:dataSources.messages.providerChangeFailed'), 'error')
    } finally { setProviderSaving(false) }
  }

  const testSource = async (id: number) => {
    if (testing !== null || providerSaving || bulkSaving || providerPaused) return
    setTesting(id)
    try {
      const result = await fetchAPI<TestResult>(`/datasources/${id}/test`, restProvider
        ? { method: 'POST', timeoutMs: 30_000 } : { method: 'POST' })
      setTestStatuses(previous => ({ ...previous, [id]: result.test_passed ? 'passed' : 'failed' }))
      setTestResult(result)
      setTestResultOpen(true)
    } catch (e) {
      toast(e instanceof Error ? e.message : t('configuration:dataSources.messages.testFailed'), 'error')
    } finally { setTesting(null) }
  }

  const resetToSeed = async () => {
    if (!(await confirmAction(t('configuration:dataSources.messages.resetConfirm'), { destructive: true }))) return
    setResetting(true)
    try {
      const result = await resetDataSourcesToSeed()
      setTestStatuses({})
      await load()
      toast(t('configuration:dataSources.messages.resetDone', { deleted: result.deleted.length, seeded: result.seeded_missing.length }), 'success')
    } catch (e) {
      toast(e instanceof Error ? e.message : t('configuration:dataSources.messages.resetFailed'), 'error')
    } finally { setResetting(false) }
  }

  const deleteSource = async () => {
    if (editId === null) return
    if (!(await confirmAction(t('configuration:dataSources.messages.deleteConfirm', { name: form.name }), { destructive: true }))) return
    try {
      await fetchAPI(`/datasources/${editId}`, { method: 'DELETE' })
      setDialogOpen(false)
      void load()
      toast(t('configuration:dataSources.messages.deleted'), 'success')
    } catch (e) { toast(e instanceof Error ? e.message : t('configuration:dataSources.messages.deleteFailed'), 'error') }
  }

  const providerMark = (id: ProviderId) => (
    <img src={`/providers/${id}.png`} alt="" width={24} height={24}
      className="size-6 shrink-0 rounded-md object-contain" />
  )

  const renderProviderButton = (id: ProviderId) => (
    <div key={id} className={`flex min-w-0 items-center gap-1 rounded-lg pr-2 transition-colors
      ${id === activeProvider ? 'bg-primary/10 text-primary' : 'text-foreground hover:bg-accent/60'}`}>
      <button type="button" aria-pressed={id === activeProvider}
        onClick={() => selectProvider(id)}
        className="flex min-h-11 min-w-0 flex-1 items-center gap-2 rounded-lg py-1.5 pl-2 text-left text-[13px] font-medium">
        {providerMark(id)}
        <span className="min-w-0 break-words">{providerName(id)}</span>
      </button>
      <Switch checked={!pausedProviders.has(id)}
        aria-label={t('configuration:dataSources.enableProvider', { name: providerName(id) })}
        disabled={providerSaving || bulkSaving || toggling !== null || testing !== null || resetting}
        onCheckedChange={enabled => void toggleProvider(id, enabled)} />
    </div>
  )

  const renderRow = (source: DataSource) => {
    const kind = source.business_type ?? source.type
    const Icon = DATASOURCE_TYPES[kind as keyof typeof DATASOURCE_TYPES]?.icon ?? Database
    const status = testing === source.id ? 'testing' : testStatuses[source.id] ?? 'untested'
    const canTest = source.source_probe !== false && !source.is_orphan
    const needsConnection = needsProviderConnection(source)
    const located = locatedSource?.id === source.id
    return (
      <tr key={source.id} data-source-id={source.id} tabIndex={located ? -1 : undefined}
        className={`border-b border-border/65 last:border-0 ${located
          ? 'bg-primary/10 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary/50'
          : 'hover:bg-accent/25'}`}>
        <td className="py-3 pl-3 pr-1 md:px-4">
          <div className="flex items-center gap-2.5">
            <span className="hidden size-8 shrink-0 place-items-center rounded-lg bg-muted/65 text-muted-foreground lg:grid">
              <Icon className="size-4" aria-hidden="true" />
            </span>
            <div className="min-w-0">
              <div className="break-words text-[13px] font-semibold">{source.name}</div>
              <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
                <span>{source.ftshare_operation?.group ?? source.tushare_operation?.group ?? typeName(kind)}</span>
                {(source.ftshare_operation?.subgroup || source.tushare_operation?.subgroup) &&
                  <span>{source.ftshare_operation?.subgroup ?? source.tushare_operation?.subgroup}</span>}
                {source.fuyao_operation && <code className="break-all">{source.fuyao_operation.path}</code>}
                {source.tushare_operation && <code className="break-all">{source.tushare_operation.id}</code>}
                {source.ftshare_operation && <FtshareTierBadge tier={source.ftshare_operation.tier} />}
                {source.supports_batch && <span>{t('configuration:dataSources.batch')}</span>}
                {source.type.startsWith('etf_') && <span>{t('configuration:dataSources.automatic')}</span>}
                {source.is_orphan && <Badge variant="destructive" className="gap-1 px-1.5 py-0.5">
                  <AlertTriangle className="size-3" aria-hidden="true" />{t('configuration:dataSources.unavailable')}
                </Badge>}
                {source.workspace_path && <a href={source.workspace_path} className="text-primary hover:underline">{t('configuration:researchData.open')}</a>}
              </div>
            </div>
          </div>
        </td>
        <td className="px-1 py-3 text-xs md:px-3">
          <span role="status" className={`inline-flex items-center gap-1.5 ${status === 'passed' ? 'text-emerald-700 dark:text-emerald-400'
            : status === 'failed' ? 'text-destructive' : 'text-muted-foreground'}`}>
            <span className="hidden size-1.5 shrink-0 rounded-full bg-current sm:inline-block" aria-hidden="true" />
            {t(canTest ? `configuration:dataSources.testStatus.${status}` : 'configuration:dataSources.testStatus.notSupported')}
          </span>
        </td>
        <td className="px-1 py-3 text-center md:px-3">
          <Switch checked={source.enabled}
            aria-label={t('configuration:dataSources.enableSource', { name: source.name })}
            disabled={providerPaused || providerSaving || bulkSaving || toggling !== null || (!source.enabled && source.provider === 'fuyao' && needsConnection)}
            onCheckedChange={() => void toggleEnabled(source)} />
        </td>
        <td className="py-3 pl-1 pr-2 md:pr-4">
          <div className="flex items-center justify-end gap-1">
            {canTest && <Button variant="ghost" size="sm" className="px-1.5 text-primary sm:px-2"
              data-tour="source-test" onClick={() => void testSource(source.id)}
              disabled={providerPaused || providerSaving || bulkSaving || testing !== null || needsConnection || !source.enabled}
              title={t('configuration:dataSources.testConnection')}
              aria-label={t('configuration:dataSources.testSource', { name: source.name })}>
              {t('configuration:dataSources.test')}
            </Button>}
            <Button variant="ghost" size="icon" className="size-8"
              data-tour="source-config" onClick={() => openDialog(source)}
              title={t('configuration:dataSources.settings')} aria-label={t('configuration:dataSources.configureSource', { name: source.name })}>
              <Pencil className="size-3.5" aria-hidden="true" />
            </Button>
          </div>
        </td>
      </tr>
    )
  }

  if (loading) {
    return <div className="flex items-center justify-center py-20" role="status">
      <span className="size-5 animate-spin rounded-full border-2 border-primary/30 border-t-primary" />
      <span className="sr-only">{t('common:states.loading')}</span>
    </div>
  }

  return (
    <div className="md:flex md:min-h-0 md:flex-1 md:flex-col">
      <header className="mb-4 flex shrink-0 flex-wrap items-start justify-between gap-3 md:mb-6">
        <div>
          <h1 className="text-[20px] font-bold tracking-tight text-foreground md:text-[22px]">{t('configuration:dataSources.title')}</h1>
          <p className="mt-1 text-xs text-muted-foreground md:text-[13px]">{t('configuration:dataSources.subtitle')}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <DataSourcesGlobalSearch entries={searchEntries} disabled={loadFailed || !searchEntries.length} onSelect={revealSource} />
          <Button variant="ghost" size="sm" disabled={providerSaving || bulkSaving || resetting || testing !== null || toggling !== null} onClick={resetToSeed}>
            <RotateCcw className={`size-3.5 ${resetting ? 'animate-spin' : ''}`} aria-hidden="true" />
            {t('configuration:dataSources.restoreDefaults')}
          </Button>
          <Button variant="outline" size="sm" disabled={loadFailed || providerSaving || bulkSaving || resetting || testing !== null || toggling !== null} onClick={() => { setOrderSearch(''); setOrderOpen(true) }}>
            <ListOrdered className="size-4" aria-hidden="true" />{t('configuration:dataSources.callOrder.title')}
          </Button>
        </div>
      </header>

      {loadFailed ? <div className="card flex items-center gap-3 p-4" role="alert">
        <span className="text-sm text-destructive">{t('configuration:dataSources.messages.loadFailed')}</span>
        <Button variant="outline" size="sm" onClick={() => void load(true)}>{t('configuration:dataProviders.retry')}</Button>
      </div> : <div className="grid gap-4 md:min-h-0 md:flex-1 md:grid-cols-[11rem_minmax(0,1fr)] md:grid-rows-[minmax(0,1fr)] lg:grid-cols-[12rem_minmax(0,1fr)]">
        <aside className="card self-start p-2 md:max-h-full md:overflow-y-auto scrollbar">
          <nav aria-label={t('configuration:dataSources.sourceNavigation')} data-tour="source-category">
            <div className="px-2 pb-2 pt-1 text-xs font-medium text-muted-foreground">{t('configuration:dataSources.sourceNavigation')}</div>
            <div className="grid grid-cols-2 gap-1 md:grid-cols-1">{PROVIDERS.map(renderProviderButton)}</div>
          </nav>
        </aside>

        <section className="card flex h-[min(34rem,65dvh)] min-h-0 min-w-0 flex-col overflow-hidden md:h-auto" aria-labelledby="data-source-provider-heading">
          <div key={`controls:${activeProvider}`} className="max-h-[55%] shrink-0 overflow-y-auto scrollbar">
            <header className="flex flex-wrap items-center gap-x-3 gap-y-2.5 px-3 py-3 md:px-4">
              <div className="mr-auto flex min-w-0 items-center gap-2.5">
                {providerMark(activeProvider)}
                <div>
                  <h2 id="data-source-provider-heading" className="break-words text-base font-semibold">{providerName(activeProvider)}</h2>
                  <p className="mt-0.5 text-xs text-muted-foreground" aria-live="polite">
                    {t('configuration:dataSources.providerCounts', {
                      total: countedEndpoints.length, enabled: providerPaused ? 0 : countedEndpoints.filter(source => source.enabled).length,
                    })}
                  </p>
                </div>
              </div>
              {hasSourceSearch && <div className="order-3 flex w-full min-w-0 items-center gap-1.5 md:order-none md:w-auto">
                <div className="min-w-0 flex-1 md:w-48 md:flex-none xl:w-56">
                  <EndpointSearchInput value={scopedSearch} label={t('configuration:dataSources.search.current')}
                    clearLabel={t('configuration:dataSources.search.clear')}
                    onChange={value => { setScopedSearch(value); setLocatedSource(null) }} />
                </div>
                {showBulkControls && <EndpointPowerMenu allOn={allEndpointsOn} allOff={allEndpointsOff} busy={bulkSaving}
                  disabled={providerPaused || providerSaving || resetting || testing !== null || toggling !== null}
                  canEnable={activeProvider !== 'fuyao' || credentialConfigured !== false}
                  onChange={enabled => void toggleAllEndpoints(enabled)} />}
              </div>}
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                {credentialConfigured !== null && <Badge variant={credentialConfigured ? 'success' : 'secondary'}>
                  {t(credentialConfigured ? 'configuration:dataSources.keyConfigured' : 'configuration:dataSources.keyRequired')}
                </Badge>}
                {restProvider && <>
                  <Button variant="ghost" size="sm" className="px-2" asChild>
                    <a href="/settings#sec-data-providers">
                      <KeyRound className="size-3.5" aria-hidden="true" />
                      {activeProvider === 'fuyao' ? t('configuration:fuyao.manageKey') : t('configuration:dataSources.manageKey')}
                    </a>
                  </Button>
                  {activeProvider === 'fuyao' && <Button variant="outline" size="sm" asChild>
                    <a href="/datasources/fuyao"><BookOpen className="size-3.5" aria-hidden="true" />{t('configuration:fuyao.rest.open')}</a>
                  </Button>}
                  {activeProvider === 'ftshare' && <Button variant="outline" size="sm" asChild>
                    <a href="/datasources/ftshare"><BookOpen className="size-3.5" aria-hidden="true" />{t('configuration:fuyao.rest.open')}</a>
                  </Button>}
                  {activeProvider === 'tushare' && <Button variant="outline" size="sm" asChild>
                    <a href="https://tushare.pro/document/2" target="_blank" rel="noopener noreferrer">
                      <BookOpen className="size-3.5" aria-hidden="true" />{t('configuration:tushare.docs')}
                    </a>
                  </Button>}
                </>}
              </div>
            </header>

            {showCategoryBar && <div className="space-y-1.5 border-t border-border/50 bg-muted/20 px-3 py-2 md:px-4">
              {restProvider && <FtshareCategoryFilters operations={restOperations} value={ftshareCategory}
                documentOrder={activeProvider === 'tushare'}
                groupName={activeProvider === 'fuyao' ? group => group === 'other' ? categoryName(group)
                  : configT(`fuyao.services.${group}`) : undefined}
                subgroupName={activeProvider === 'fuyao' ? typeName : undefined}
                onChange={value => { setFtshareCategory(value); setLocatedSource(null) }} />}
              {activeProvider === 'ftshare' && <div className="flex flex-wrap gap-1" role="group" aria-label={t('configuration:ftshare.tierFilter')}>
                {(['all', 'free', 'basic'] as const).map(plan => <Button key={plan} variant="ghost" size="sm"
                  aria-pressed={plan === ftshareTier} onClick={() => { setFtshareTier(plan); setLocatedSource(null) }}
                  className={plan === ftshareTier ? 'bg-primary/10 text-primary hover:bg-primary/10 hover:text-primary' : ''}>
                  {t(plan === 'all' ? 'configuration:ftshare.allTiers' : `configuration:ftshare.tiers.${plan}`)}
                </Button>)}
              </div>}
              {!restProvider && categories.length > 2 && <div className="flex flex-wrap gap-1"
                role="group" aria-label={t('configuration:dataSources.categoryFilter')}>
                {categories.map(id => <Button key={id} variant="ghost" size="sm"
                  aria-pressed={id === activeCategory} onClick={() => { setCategory(id); setLocatedSource(null) }}
                  className={id === activeCategory ? 'bg-primary/10 text-primary hover:bg-primary/10 hover:text-primary' : ''}>{categoryName(id)}</Button>)}
              </div>}
            </div>}
          </div>

          <div key={`${activeProvider}:${activeCategory}:${ftshareTier}:${ftshareCategory.group}:${ftshareCategory.subgroup}:${scopedSearch}`}
            ref={endpointList} role="region" tabIndex={0}
            aria-label={t('configuration:dataSources.endpointList')}
            className="min-h-0 flex-1 overflow-y-auto overscroll-contain scroll-pt-8 scrollbar focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary/50">
            {providerSources.length === 0 ? <div className="border-t border-border/65 px-4 py-10 text-center text-sm text-muted-foreground">
              {t('configuration:dataSources.emptyProvider')}
            </div> : !visibleSources.length ? <p className="border-t border-border/65 px-4 py-10 text-center text-sm text-muted-foreground">
              {t('configuration:fuyao.rest.empty')}
            </p> : (
              <table className="w-full table-fixed border-collapse" aria-labelledby="data-source-provider-heading">
                <thead className="sticky top-0 z-10 bg-muted text-left text-[11px] text-muted-foreground shadow-[inset_0_1px_0_hsl(var(--border)/0.65),inset_0_-1px_0_hsl(var(--border)/0.65)]">
                  <tr>
                    <th scope="col" className="py-2 pl-3 pr-1 font-medium md:px-4">{t('configuration:dataSources.columns.endpoint')}</th>
                    <th scope="col" className="w-16 px-1 py-2 font-medium md:w-24 md:px-3">{t('configuration:dataSources.columns.test')}</th>
                    <th scope="col" className="w-12 px-1 py-2 text-center font-medium md:w-16 md:px-3">{t('configuration:dataSources.columns.enabled')}</th>
                    <th scope="col" className="w-20 py-2 pr-2 text-right font-medium md:w-24 md:pr-4">{t('configuration:dataSources.columns.actions')}</th>
                  </tr>
                </thead>
                <tbody>{visibleSources.map(renderRow)}</tbody>
              </table>
            )}
          </div>
        </section>
      </div>}

      <Dialog open={orderOpen} onOpenChange={setOrderOpen}>
        <DialogContent className="top-1/2 flex max-h-[86dvh] max-w-2xl -translate-y-1/2 flex-col gap-4 overflow-hidden p-4 sm:p-6">
          <DialogHeader className="mb-0 pr-8">
            <DialogTitle>{t('configuration:dataSources.callOrder.title')}</DialogTitle>
            <DialogDescription>{t('configuration:dataSources.callOrder.description')}</DialogDescription>
          </DialogHeader>
          <EndpointSearchInput label={t('configuration:dataSources.callOrder.search')} value={orderSearch} onChange={setOrderSearch} />
          {orderTypes.length === 0 ? <p className="py-8 text-center text-sm text-muted-foreground">
            {t('configuration:dataSources.callOrder.empty')}
          </p> : <>
            <div className="flex items-end gap-2">
              <div className="min-w-0 flex-1 space-y-1.5">
                <Label htmlFor="data-source-order-type">{t('configuration:dataSources.callOrder.type')}</Label>
                <Select value={activeOrderType} onValueChange={setOrderType}>
                  <SelectTrigger id="data-source-order-type"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {(['fallback', 'aggregate', 'direct'] as const).map(mode => {
                      const keys = orderTypes.filter(key => byRouting.get(key)?.mode === mode)
                      return keys.length > 0 && <SelectGroup key={mode}>
                        <SelectLabel>{t(`configuration:dataSources.callOrder.modes.${mode}`)}</SelectLabel>
                        {keys.map(key => <SelectItem value={key} key={key}>{byRouting.get(key)?.label}</SelectItem>)}
                      </SelectGroup>
                    })}
                  </SelectContent>
                </Select>
              </div>
              {orderGroup && <Badge variant="secondary" className="mb-2 shrink-0">
                {t(`configuration:dataSources.callOrder.modes.${orderGroup.mode}`)}
              </Badge>}
            </div>
            <ol className="min-h-0 space-y-2 overflow-y-auto overscroll-contain scrollbar"
              aria-label={t('configuration:dataSources.callOrder.title')}>
              {orderRows.map(source => {
                const provider = providerOf(source)
                const status = orderStatus(source)
                const role = orderGroup?.mode === 'fallback' ? provider === 'ftshare' ? 'primary' : 'backup' : null
                const isPrimary = role === 'primary'
                return (
                  <li key={source.id} className={`flex items-center gap-2 rounded-xl border px-2 py-2.5 sm:gap-3 sm:px-3
                    ${isPrimary ? 'border-primary/30 bg-primary/5' : 'border-border/65 bg-background/45'}`}>
                    {isProvider(provider) && providerMark(provider)}
                    <div className="min-w-0 flex-1">
                      <p className="break-words text-[13px] font-medium">{source.name}</p>
                      <p className="break-words text-xs text-muted-foreground">{[providerName(provider),
                        ...(source.routing?.markets ?? []).map(market => configT(`dataSources.callOrder.markets.${market}`, { defaultValue: market })),
                      ].join(' · ')}</p>
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-1 sm:flex-row sm:items-center">
                      {role && <Badge variant={isPrimary ? 'default' : 'outline'}>
                        {t(`configuration:dataSources.callOrder.${role}`)}
                      </Badge>}
                      {(!role || status !== 'enabled') && <Badge variant={status === 'enabled' ? 'outline' : 'secondary'}>
                        {t(`configuration:dataSources.callOrder.${status}`)}
                      </Badge>}
                    </div>
                  </li>
                )
              })}
            </ol>
          </>}
          <div className="flex justify-end">
            <Button size="sm" variant="outline" onClick={() => setOrderOpen(false)}>
              {t('configuration:dataSources.callOrder.done')}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Source settings */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent data-tour="source-config-dialog"
          className={form.ftshareOperation || catalogOperation ? 'scrollbar max-h-[85dvh] max-w-2xl overflow-y-auto' : undefined}><div data-tour-instructions />
          <DialogHeader>
            <DialogTitle>{t('configuration:dataSources.form.title', { name: form.name })}</DialogTitle>
            <DialogDescription>{providerName(form.providerGroup ?? form.provider)} · {form.ftshareOperation?.group ?? form.fuyaoOperation?.path ?? form.tushareOperation?.id ?? typeName(form.type)}</DialogDescription>
          </DialogHeader>
          {form.ftshareOperation ? <form className="space-y-4" onSubmit={event => { event.preventDefault(); void saveSource() }}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <FtshareTierBadge tier={form.ftshareOperation.tier} />
              <a href={form.ftshareOperation.docs_url} target="_blank" rel="noopener noreferrer" className="text-xs text-primary hover:underline">
                {t('configuration:fuyao.rest.officialDocs')}
              </a>
            </div>
            <FtshareParameters operation={form.ftshareOperation} value={ftshareSettings} onChange={setFtshareSettings} />
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => setDialogOpen(false)}>{t('common:actions.cancel')}</Button>
              <Button type="submit">{t('common:actions.save')}</Button>
            </div>
          </form> : catalogOperation ? <form className="space-y-4" onSubmit={event => { event.preventDefault(); void saveSource() }}>
            <a href={catalogOperation.docs_url} target="_blank" rel="noopener noreferrer" className="text-xs text-primary hover:underline">
              {t('configuration:fuyao.rest.officialDocs')}
            </a>
            <FuyaoParameters operation={catalogOperation} value={catalogParams} onChange={setCatalogParams} />
            {form.tushareOperation && <div className="space-y-2">
              {form.tushareOperation.require_any && <p className="text-xs text-muted-foreground">
                {t('configuration:tushare.requireAny', { names: form.tushareOperation.require_any.join(', ') })}
              </p>}
              <Label htmlFor="tushare-return-fields">{t('configuration:tushare.fields')}</Label>
              <Input id="tushare-return-fields" value={tushareFields} maxLength={16_384}
                placeholder={t('configuration:tushare.fieldsPlaceholder')} onChange={event => setTushareFields(event.target.value)} />
            </div>}
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => setDialogOpen(false)}>{t('common:actions.cancel')}</Button>
              <Button type="submit">{t('common:actions.save')}</Button>
            </div>
          </form> : <form className="space-y-4 mt-2" onSubmit={event => { event.preventDefault(); void saveSource() }}>
            {form.testSettings ? <SourceTestParameters settings={form.testSettings} symbols={testSymbolsInput}
              onSymbolsChange={setTestSymbolsInput} values={probeParams} onChange={setProbeParams} /> : <>
              <div>
                <Label htmlFor="source-test-symbols">{t('configuration:dataSources.form.testSymbols')} <span className="text-muted-foreground font-normal">{t('configuration:dataSources.form.commaSeparated')}</span></Label>
                <Input
                  id="source-test-symbols"
                  value={testSymbolsInput}
                  onChange={e => setTestSymbolsInput(e.target.value)}
                  placeholder={t('configuration:dataSources.form.symbolsPlaceholder')}
                />
              </div>

              {/* 高级:完整 JSON 编辑(只读形式,展开后可编辑) */}
              {Object.keys(form.config || {}).length > 0 && (
                <details className="text-[12px]">
                  <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
                    {t('configuration:dataSources.form.advanced')}
                  </summary>
                  <textarea
                    className="mt-2 w-full font-mono text-[11px] p-2 border border-border rounded bg-background min-h-[100px]"
                    value={JSON.stringify(form.config || {}, null, 2)}
                    onChange={e => {
                      try {
                        const parsed = JSON.parse(e.target.value)
                        setForm({ ...form, config: parsed })
                      } catch {
                        // 解析失败时不更新,允许用户继续输入
                      }
                    }}
                  />
                </details>
              )}
            </>}
            <div className="flex justify-between gap-2 pt-2">
              <Button type="button" variant="ghost" className="text-red-500 hover:text-red-600" onClick={deleteSource}>
                <Trash2 className="w-4 h-4 mr-1" />{t('common:actions.delete')}
              </Button>
              <div className="flex gap-2">
                <Button type="button" variant="ghost" onClick={() => setDialogOpen(false)}>{t('common:actions.cancel')}</Button>
                <Button type="submit">{t('common:actions.save')}</Button>
              </div>
            </div>
          </form>}
        </DialogContent>
      </Dialog>

      {/* Test Result Dialog */}
      <Dialog open={testResultOpen} onOpenChange={setTestResultOpen}>
        <DialogContent data-tour="source-test-dialog"
          className="max-w-2xl w-[92vw] max-h-[85vh] overflow-y-auto scrollbar"
          onInteractOutside={(e) => e.preventDefault()}
        >
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {testResult?.test_passed ? (
                <Check className="w-5 h-5 text-emerald-500" />
              ) : (
                <X className="w-5 h-5 text-red-500" />
              )}
              {t('configuration:dataSources.result.title', { name: testResult?.source_name || '' })}
            </DialogTitle>
            <DialogDescription>
              {testResult?.type_label} · {testResult?.provider}
              {testResult?.supports_batch && t('configuration:dataSources.result.batchSupported')}
              {testResult?.ftshare_tier && ` · ${t(`configuration:ftshare.tiers.${testResult.ftshare_tier}`)}`}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 mt-2 pr-1"><div data-tour-instructions />
            {/* Summary */}
            <div className="flex items-center gap-4 p-3 rounded-lg bg-accent/30">
              <div className="flex-1">
                <div className="text-[11px] text-muted-foreground">{t('configuration:dataSources.result.status')}</div>
                <div className={`text-[13px] font-medium ${testResult?.test_passed ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-500'}`}>
                  {testResult?.test_passed ? t('configuration:dataSources.result.success') : t('configuration:dataSources.result.failed')}
                </div>
              </div>
              {(testResult?.http_status === undefined || testResult?.provider === 'tushare') && <div className="flex-1">
                <div className="text-[11px] text-muted-foreground">{t('configuration:dataSources.result.count')}</div>
                <div className="text-[13px] font-medium">{t('configuration:dataSources.result.rows', { count: testResult?.count ?? 0 })}</div>
              </div>}
              <div className="flex-1">
                <div className="text-[11px] text-muted-foreground">{t('configuration:dataSources.result.duration')}</div>
                <div className="text-[13px] font-medium">{testResult?.duration_ms ?? 0} ms</div>
              </div>
            </div>

            {/* Error message */}
            {testResult?.error && (
              <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20">
                <div className="text-[11px] text-red-500 font-medium mb-1">{t('configuration:dataSources.result.error')}</div>
                <div className="text-[12px] text-red-600 dark:text-red-400 break-words whitespace-pre-wrap">{testResult.error}</div>
              </div>
            )}

            {testResult?.errors && <TestErrorList errors={testResult.errors} />}
            {testResult?.http_status !== undefined && <FtshareResponse
              name={testResult.source_type.replace(/^(ftshare|fuyao|tushare):/, '')} successful={testResult.test_passed}
              result={{ http_status: testResult.http_status, business_code: testResult.business_code ?? null,
                response_json: testResult.raw_response ?? null, message: testResult.error ?? null }} />}

            {/* Execution Logs */}
            {testResult?.logs && testResult.logs.length > 0 && (
              <div>
                <div className="text-[12px] font-medium text-foreground mb-2 flex items-center gap-1.5">
                  <Clock className="w-3.5 h-3.5" />
                  {t('configuration:dataSources.result.logs')}
                </div>
                <div className="space-y-1.5 max-h-40 overflow-y-auto scrollbar">
                  {testResult.logs.map((log, i) => (
                    <div key={i} className="flex items-start gap-2 p-2 rounded-lg bg-accent/30 text-[11px]">
                      <span className="text-muted-foreground font-mono flex-shrink-0">{log.timestamp}</span>
                      <span className={`px-1 py-0.5 rounded text-[10px] flex-shrink-0 ${
                        log.action === 'start' ? 'bg-blue-500/10 text-blue-500' :
                        log.action === 'success' ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400' :
                        'bg-red-500/10 text-red-500'
                      }`}>
                        {t(`configuration:dataSources.result.actions.${log.action}`)}
                      </span>
                      <span className="text-foreground flex-1">{log.message}</span>
                      {log.duration_ms > 0 && (
                        <span className="text-muted-foreground flex-shrink-0">{log.duration_ms}ms</span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Data Preview */}
            {/* Chart type - show image outside scrollable area */}
            {testResult?.test_passed && testResult.source_type === 'chart' && (testResult.items as {image?: string})?.image && (
              <div>
                <div className="text-[12px] font-medium text-foreground mb-2">{t('configuration:dataSources.result.preview')}</div>
                <div className="rounded-lg overflow-hidden border">
                  <img src={(testResult.items as {image: string}).image} alt={t('configuration:dataSources.result.chartAlt')} className="w-full" />
                </div>
              </div>
            )}

            {/* Other data types - in scrollable container */}
            {testResult?.test_passed && testResult.items && testResult.source_type !== 'chart' && Array.isArray(testResult.items) && testResult.items.length > 0 && (
              <div>
                <div className="text-[12px] font-medium text-foreground mb-2">{t('configuration:dataSources.result.preview')}</div>
                <div className="space-y-1.5 max-h-60 overflow-y-auto scrollbar">

                  {/* News type */}
                  {testResult.source_type === 'news' && testResult.items.map((item, i) => {
                    const newsItem = item as { title?: string; time?: string }
                    return (
                      <div key={i} className="flex items-start gap-2 p-2 rounded-lg bg-accent/30">
                        <span className="text-[12px] text-foreground flex-1">{newsItem.title}</span>
                        <span className="text-[11px] text-muted-foreground flex-shrink-0">{newsItem.time}</span>
                      </div>
                    )
                  })}

                  {/* Events type */}
                  {testResult.source_type === 'events' && testResult.items.map((item, i) => {
                    const ev = item as { title?: string; time?: string; event_type?: string }
                    return (
                      <div key={i} className="flex items-start gap-2 p-2 rounded-lg bg-accent/30">
                        <span className="text-[11px] font-mono text-muted-foreground/80 flex-shrink-0">{ev.event_type || 'notice'}</span>
                        <span className="text-[12px] text-foreground flex-1">{ev.title}</span>
                        <span className="text-[11px] text-muted-foreground flex-shrink-0">{ev.time}</span>
                      </div>
                    )
                  })}

                  {/* Quote type */}
                  {testResult.source_type === 'quote' && testResult.items.map((item, i) => {
                    const quoteItem = item as { symbol?: string; name?: string; price?: number; change_pct?: number }
                    return (
                      <div key={i} className="flex items-center justify-between p-2 rounded-lg bg-accent/30">
                        <span className="text-[12px] font-medium text-foreground">{quoteItem.name || quoteItem.symbol}</span>
                        <div className="flex items-center gap-3">
                          <span className="text-[12px] font-mono">{quoteItem.price?.toFixed(2)}</span>
                          <span className={`text-[11px] font-medium ${
                            marketSignTextClass(quoteItem.change_pct)
                          }`}>
                            {(quoteItem.change_pct ?? 0) > 0 ? '+' : ''}{quoteItem.change_pct?.toFixed(2)}%
                          </span>
                        </div>
                      </div>
                    )
                  })}

                  {/* Kline type */}
                  {testResult.source_type === 'kline' && testResult.items.map((item, i) => {
                    const klineItem = item as { symbol?: string; last_close?: number; trend?: string }
                    return (
                      <div key={i} className="flex items-center justify-between p-2 rounded-lg bg-accent/30">
                        <span className="text-[12px] font-medium text-foreground">{klineItem.symbol}</span>
                        <div className="flex items-center gap-3">
                          <span className="text-[12px] font-mono">{klineItem.last_close?.toFixed(2)}</span>
                          <span className="text-[11px] text-muted-foreground">{klineItem.trend}</span>
                        </div>
                      </div>
                    )
                  })}

                  {/* Flash news type */}
                  {testResult.source_type === 'flash_news' && testResult.items.map((item, i) => {
                    const flashItem = item as { title?: string; time?: string; symbols?: string[] }
                    return (
                      <div key={i} className="flex items-start gap-2 p-2 rounded-lg bg-accent/30">
                        <span className="text-[12px] text-foreground flex-1">
                          {flashItem.title}
                          {flashItem.symbols && flashItem.symbols.length > 0 && (
                            <span className="ml-2 text-[11px] text-muted-foreground">{flashItem.symbols.join(', ')}</span>
                          )}
                        </span>
                        <span className="text-[11px] text-muted-foreground flex-shrink-0">{flashItem.time}</span>
                      </div>
                    )
                  })}

                  {/* Fundamentals type */}
                  {testResult.source_type === 'fundamentals' && testResult.items.map((item, i) => {
                    const fundItem = item as { symbol?: string; name?: string; pe_ttm?: number; pb?: number; roe?: number }
                    return (
                      <div key={i} className="flex items-center justify-between p-2 rounded-lg bg-accent/30">
                        <span className="text-[12px] font-medium text-foreground">{fundItem.name || fundItem.symbol}</span>
                        <div className="flex items-center gap-3">
                          <span className="text-[11px] text-muted-foreground">PE {fundItem.pe_ttm?.toFixed(2) ?? '-'}</span>
                          <span className="text-[11px] text-muted-foreground">PB {fundItem.pb?.toFixed(2) ?? '-'}</span>
                          <span className="text-[11px] text-muted-foreground">ROE {fundItem.roe?.toFixed(2) ?? '-'}%</span>
                        </div>
                      </div>
                    )
                  })}

                  {/* Capital flow type */}
                  {testResult.source_type === 'capital_flow' && testResult.items.map((item, i) => {
                    const flowItem = item as { symbol?: string; name?: string; main_net?: number; main_pct?: number }
                    return (
                      <div key={i} className="flex items-center justify-between p-2 rounded-lg bg-accent/30">
                        <span className="text-[12px] font-medium text-foreground">{flowItem.name || flowItem.symbol}</span>
                        <div className="flex items-center gap-3">
                          <span className={`text-[12px] font-mono ${
                            marketSignTextClass(flowItem.main_net)
                          }`}>
                            {(flowItem.main_net ?? 0) > 0 ? '+' : ''}{formatNumber(flowItem.main_net ?? 0, { notation: 'compact', maximumFractionDigits: 2 })}
                          </span>
                          <span className="text-[11px] text-muted-foreground">
                            {flowItem.main_pct?.toFixed(2)}%
                          </span>
                        </div>
                      </div>
                    )
                  })}

                  {/* Dragon tiger type */}
                  {testResult.source_type === 'dragon_tiger' && testResult.items.map((item, i) => {
                    const dtItem = item as { symbol?: string; name?: string; net_buy?: number }
                    return (
                      <div key={i} className="flex items-center justify-between p-2 rounded-lg bg-accent/30">
                        <span className="text-[12px] font-medium text-foreground">{dtItem.name || dtItem.symbol}</span>
                        <span className={`text-[12px] font-mono ${
                          marketSignTextClass(dtItem.net_buy)
                        }`}>
                          {(dtItem.net_buy ?? 0) > 0 ? '+' : ''}{formatNumber(dtItem.net_buy ?? 0, { notation: 'compact', maximumFractionDigits: 2 })}
                        </span>
                      </div>
                    )
                  })}

                  {/* Margin type */}
                  {testResult.source_type === 'margin' && testResult.items.map((item, i) => {
                    const marginItem = item as { symbol?: string; date?: string; total_balance?: number }
                    return (
                      <div key={i} className="flex items-center justify-between p-2 rounded-lg bg-accent/30">
                        <span className="text-[12px] font-medium text-foreground">{marginItem.symbol}</span>
                        <div className="flex items-center gap-3">
                          <span className="text-[12px] font-mono">{formatNumber(marginItem.total_balance ?? 0, { notation: 'compact', maximumFractionDigits: 2 })}</span>
                          <span className="text-[11px] text-muted-foreground">{marginItem.date}</span>
                        </div>
                      </div>
                    )
                  })}

                  {/* Shareholders type */}
                  {testResult.source_type === 'shareholders' && testResult.items.map((item, i) => {
                    const shItem = item as { symbol?: string; report_date?: string; holder_num?: number }
                    return (
                      <div key={i} className="flex items-center justify-between p-2 rounded-lg bg-accent/30">
                        <span className="text-[12px] font-medium text-foreground">{shItem.symbol}</span>
                        <div className="flex items-center gap-3">
                          <span className="text-[12px] font-mono">{shItem.holder_num != null ? formatNumber(shItem.holder_num) : '-'}</span>
                          <span className="text-[11px] text-muted-foreground">{shItem.report_date}</span>
                        </div>
                      </div>
                    )
                  })}

                  {/* Dividend type */}
                  {testResult.source_type === 'dividend' && testResult.items.map((item, i) => {
                    const divItem = item as { symbol?: string; ex_date?: string; dividend_per_share?: number }
                    return (
                      <div key={i} className="flex items-center justify-between p-2 rounded-lg bg-accent/30">
                        <span className="text-[12px] font-medium text-foreground">{divItem.symbol}</span>
                        <div className="flex items-center gap-3">
                          <span className="text-[12px] font-mono">{divItem.dividend_per_share?.toFixed(4) ?? '-'} {t('configuration:dataSources.result.cnyPerShare')}</span>
                          <span className="text-[11px] text-muted-foreground">{divItem.ex_date}</span>
                        </div>
                      </div>
                    )
                  })}

                  {/* Northbound type */}
                  {testResult.source_type === 'northbound' && testResult.items.map((item, i) => {
                    const nbItem = item as { date?: string; hgt_net?: number; total_net?: number }
                    return (
                      <div key={i} className="flex items-center justify-between p-2 rounded-lg bg-accent/30">
                        <span className="text-[12px] font-medium text-foreground">{nbItem.date}</span>
                        <div className="flex items-center gap-3">
                          <span className={`text-[12px] font-mono ${
                            marketSignTextClass(nbItem.total_net)
                          }`}>
                            {(nbItem.total_net ?? 0) > 0 ? '+' : ''}{formatNumber(nbItem.total_net ?? 0, { notation: 'compact', maximumFractionDigits: 2 })}
                          </span>
                          <span className="text-[11px] text-muted-foreground">
                            {t('configuration:dataSources.result.shanghaiConnect', { value: formatNumber(nbItem.hgt_net ?? 0, { notation: 'compact', maximumFractionDigits: 2 }) })}
                          </span>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {/* Test symbols info */}
            {testResult?.test_symbols && testResult.test_symbols.length > 0 && (
              <div className="text-[11px] text-muted-foreground">
                {t('configuration:dataSources.result.testSymbols', { symbols: testResult.test_symbols.join(', ') })}
              </div>
            )}
            {testResult?.test_params && Object.entries(testResult.test_params).some(([, value]) => value !== null) && (
              <dl className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
                {Object.entries(testResult.test_params).filter(([, value]) => value !== null).map(([key, value]) => (
                  <div key={key} className="flex gap-1.5">
                    <dt>{configT(`configuration:dataSources.probeParams.fields.${key}.label`, { defaultValue: key })}</dt>
                    <dd className="font-mono text-foreground">{String(value)}</dd>
                  </div>
                ))}
              </dl>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
