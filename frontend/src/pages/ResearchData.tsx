import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, NavLink, useParams, useSearchParams } from 'react-router-dom'
import { ArrowRight, Database, Search } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  loadResearchView, loadResearchWorkspace, researchWorkspaces,
  type BacktestConditions, type FuyaoParameter, type ResearchManifest, type ResearchResult, type ResearchView, type ResearchWorkspace,
} from '@panwatch/api'
import { Badge } from '@panwatch/base-ui/components/ui/badge'
import { Button } from '@panwatch/base-ui/components/ui/button'
import { Input } from '@panwatch/base-ui/components/ui/input'
import { Label } from '@panwatch/base-ui/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@panwatch/base-ui/components/ui/select'
import { BacktestRules, backtestReady, blankRule } from '@/components/research/BacktestRules'
import { asRow, exchangeDate, fieldLabel, ResearchChart, ResearchDataset, type ResearchLink, type Row } from '@/components/research/ResearchDataset'

const OMIT = '__omit__'
const inherited = ['thscode', 'manager_id', 'company_id', 'issue_code', 'variety', 'company', 'report_type'] as const
const dateFields = new Set(['date', 'start_date', 'end_date', 'trade_date'])
type Filters = Record<string, string>
type Translate = (key: string, options?: Record<string, unknown>) => string

function isDate(field: FuyaoParameter) {
  return field.encoding === 'date-ms' || dateFields.has(field.name)
}

function recent(day: string, offset: number) {
  return new Date(Date.parse(day + 'T00:00:00Z') - offset * 86_400_000).toISOString().slice(0, 10)
}

function initialFilters(kind: ResearchWorkspace, view: ResearchView, manifest: ResearchManifest, params: URLSearchParams, context: Filters) {
  return Object.fromEntries(view.fields.map(field => {
    const key = field.name
    const explicit = params.get(key) || context[key]
    if (explicit) return [key, explicit]
    if (key === 'thscode' && kind.startsWith('fund_')) return [key, kind === 'fund_backtest' ? '000001.OF' : '510300.SH']
    if (key === 'thscode' && kind === 'etf_adjusted_history') return [key, '510300.SH']
    if (key === 'thscodes' && kind === 'etf_adjusted_history') return [key, '510300.SH,159915.SZ']
    if (key === 'thscode' && view.id === 'membership') return [key, '600519.SH']
    if (key === 'issue_code' || key === 'manager_id' || key === 'company_id' ||
        (key === 'thscode' && (kind === 'futures_research' || kind === 'options_research' || view.id === 'members')) ||
        (key === 'end_date' && kind === 'fund_holdings')) return [key, '']
    if (field.encoding === 'date-ms') return [key, field.required ? key === 'start' ? recent(manifest.today, 90) : manifest.today : '']
    if (dateFields.has(key) && field.required) return [key, key === 'start_date' ? recent(manifest.today, 30) : manifest.last_trade_date || '']
    if (key === 'market' && kind === 'ipo') return [key, 'sh_sz']
    if (field.required && field.example !== undefined) return [key, String(field.example)]
    return [key, field.default === undefined ? '' : String(field.default)]
  }))
}

function businessParams(view: ResearchView, values: Filters) {
  const filters: Filters = {}
  for (const field of view.fields) {
    const value = values[field.name]?.trim()
    if (!value) continue
    if (field.encoding === 'date-ms') {
      const end = field.name === 'end'
      filters[field.name] = String(Date.parse(`${value}T${end ? '23:59:59.999' : '00:00:00'}+08:00`))
    } else {
      filters[field.name] = value
    }
  }
  return filters
}

function selection(kind: ResearchWorkspace, view: string, filters: Filters = {}) {
  return `/market-data/${kind}?${new URLSearchParams({ ...filters, view })}`
}

function drilldown(kind: ResearchWorkspace, view: string, row: Row, values: Filters, t: Translate): ResearchLink[] {
  const result: ResearchLink[] = []
  const text = (value: unknown) => typeof value === 'string' || (typeof value === 'number' && Number.isSafeInteger(value)) ? String(value) : ''
  const symbol = text(row.thscode)
  const add = (id: string, target: string, args: Filters) => result.push({ label: t(`researchData.${id}`), to: selection(kind, target, args) })
  if (kind === 'index_constituents' && (view === 'directory' || view === 'membership') && symbol.endsWith('.TI')) {
    add('constituents', 'members', { thscode: symbol })
  }
  if (kind === 'ipo' && view === 'calendar' && text(row.issue_code)) add('details', 'issue', { issue_code: text(row.issue_code) })
  if (kind === 'fund_holdings' && /^(stock|bond)-reports$/.test(view) && text(row.report_type) && typeof row.end_date_ms === 'number') {
    add('holdings', view.replace('reports', 'positions'), {
      thscode: values.thscode, report_type: text(row.report_type), end_date: exchangeDate(row.end_date_ms),
    })
  }
  if (kind === 'fund_research') {
    if (text(row.manager_id) && view !== 'manager') add('manager', 'manager', { manager_id: text(row.manager_id) })
    if (text(row.company_id) && view !== 'company') add('company', 'company', { company_id: text(row.company_id) })
    if (symbol && (view === 'offerings' || view === 'qdii-funds')) add('details', 'profile', { thscode: symbol })
  }
  if ((kind === 'futures_research' || kind === 'options_research') && symbol.includes('.')) {
    const context = { thscode: symbol, ...(text(row.variety_code) ? { variety: text(row.variety_code) } : {}) }
    if (view !== 'contract') add('details', 'contract', context)
    if (view !== 'bars') add('bars', 'bars', context)
    if (view === 'latest-basis' && text(row.spot_indicator_id)) {
      add('basisHistory', 'basis-history', { thscode: symbol, spot_indicator_id: text(row.spot_indicator_id) })
    }
  }
  if (kind === 'futures_research' && text(row.company_name) && values.thscode && values.variety && view !== 'position-history') {
    add('positionHistory', 'position-history', { thscode: values.thscode, variety: values.variety, company: text(row.company_name) })
  }
  return result
}

function Field({ field, value, onChange, t }: { field: FuyaoParameter; value: string; onChange: (v: string) => void; t: Translate }) {
  const id = `research-${field.name}`
  const label = fieldLabel(field.name, t)
  const options = field.enum ?? (field.type === 'boolean' ? ['true', 'false'] : undefined)
  return <div className="min-w-0 space-y-1.5">
    <Label htmlFor={id} id={`${id}-label`}>{label}{field.required && <span className="ml-1 text-primary">*</span>}</Label>
    {options ? <Select value={value || OMIT} onValueChange={next => onChange(next === OMIT ? '' : next)}>
      <SelectTrigger id={id} aria-labelledby={`${id}-label`} aria-describedby={`${id}-hint`}><SelectValue /></SelectTrigger>
      <SelectContent><SelectItem value={OMIT}>{t('researchData.unset')}</SelectItem>
        {options.map(option => <SelectItem key={option} value={option}>{t(`researchData.choices.${option}`, { defaultValue: option })}</SelectItem>)}
      </SelectContent>
    </Select> : <Input id={id} aria-describedby={`${id}-hint`} required={field.required} value={value}
      onChange={event => onChange(event.target.value)} type={isDate(field) ? 'date' : 'text'} maxLength={2000}
      placeholder={field.example === undefined ? undefined : String(field.example)}
      inputMode={field.type === 'number' ? 'decimal' : field.type === 'integer' && !isDate(field) ? 'numeric' : undefined} />}
    <p id={`${id}-hint`} className="text-xs leading-relaxed text-muted-foreground">{field.description}</p>
  </div>
}

function ViewPanel({ kind, view, manifest, params, context, remember }: {
  kind: ResearchWorkspace; view: ResearchView; manifest: ResearchManifest; params: URLSearchParams; context: Filters
  remember: (key: string, value: string) => void
}) {
  const { t: translate } = useTranslation('configuration')
  const t = translate as Translate
  const [values, setValues] = useState(() => initialFilters(kind, view, manifest, params, context))
  const [conditions, setConditions] = useState<BacktestConditions>(() => ({ buy: [blankRule()], sell: [blankRule()] }))
  const [indicators, setIndicators] = useState<unknown>(null)
  const [result, setResult] = useState<ResearchResult | null>(null)
  const [usedFilters, setUsedFilters] = useState<Filters>({})
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [generation, setGeneration] = useState(0)
  const active = manifest.sources.some(source => source.enabled && source.available)
  const strategy = view.id === 'strategy'
  const pending = useRef<AbortController | null>(null)
  const requiredReady = view.fields.every(field => !field.required || values[field.name]?.trim())

  async function read(input: Filters, rules?: BacktestConditions) {
    pending.current?.abort()
    const controller = new AbortController()
    pending.current = controller
    setLoading(true)
    setError('')
    setResult(null)
    try {
      const response = await loadResearchView(kind, view.id, businessParams(view, input), controller.signal, rules)
      if (!controller.signal.aborted) { setResult(response); setUsedFilters(input); setGeneration(n => n + 1) }
    } catch (err) {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : t('researchData.loadError'))
    } finally { if (!controller.signal.aborted) setLoading(false) }
  }

  useEffect(() => {
    if (active && !strategy && requiredReady) void read(values)
    return () => pending.current?.abort()
  }, [active])
  useEffect(() => {
    if (!active || !strategy) return
    const controller = new AbortController()
    loadResearchView(kind, 'indicators', {}, controller.signal).then(response => {
      if (!controller.signal.aborted) setIndicators(response.result)
    }).catch(err => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : t('researchData.loadError')) })
    return () => controller.abort()
  }, [active, strategy])

  function change(key: string, value: string) {
    setValues(old => ({ ...old, [key]: value }))
    if (inherited.some(field => field === key)) remember(key, value)
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    if (!active || !requiredReady || strategy && !backtestReady(conditions)) return
    const convert = (rules: BacktestConditions['buy']) => rules.map(rule => {
      const value = String(rule.value).trim()
      return { ...rule, value: Number.isFinite(Number(value)) ? Number(value) : value }
    })
    void read(values, strategy ? { buy: convert(conditions.buy), sell: convert(conditions.sell) } : undefined)
  }

  const root = asRow(result?.result)
  const cursor = root?.has_more === true && typeof root.offset === 'string' ? root.offset : undefined
  const queryPage = asRow(root?.pagination)
  const page = Number(queryPage?.page || usedFilters.page || 1)
  const maxPages = Number(queryPage?.pages ?? queryPage?.total_pages ?? 0)
  const hasNext = Number.isFinite(page) && page < maxPages && view.fields.some(f => f.name === 'page')
  const offset = Number(usedFilters.offset || 0)
  const size = Number(usedFilters.limit || 100)
  const numericOffset = !cursor && typeof root?.total === 'number' && (offset + size) < root.total &&
    view.fields.some(f => f.name === 'offset' && f.type === 'integer')
  return <article className="card min-w-0 space-y-5 p-4 md:p-6">
    <div>
      <h2 className="text-lg font-semibold">{t(`researchData.views.${kind}.${view.id}`, { defaultValue: view.title })}</h2>
      <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{view.description}</p>
      {kind === 'etf_adjusted_history' && <p className="mt-2 text-xs text-muted-foreground">{t('researchData.adjusted')}</p>}
      {strategy && <p className="mt-2 text-xs text-muted-foreground">{t('researchData.backtestNote')}</p>}
    </div>
    {!active && <div className="rounded-lg border border-border/70 bg-muted/30 p-4 text-sm" role="status">
      <p>{t('researchData.disabled')}</p>
      <Link className="mt-2 inline-block text-primary hover:underline" to="/datasources">{t('researchData.configure')}</Link>
    </div>}
    {active && <form onSubmit={submit} className="space-y-4 border-t border-border/60 pt-4">
      {!!view.fields.length && <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{view.fields.map(field =>
        <Field key={field.name} field={field} value={values[field.name] || ''} onChange={value => change(field.name, value)} t={t} />
      )}</div>}
      {strategy && <BacktestRules indicators={indicators} value={conditions} onChange={setConditions} />}
      <Button size="sm" type="submit" disabled={loading || !requiredReady || strategy && !backtestReady(conditions)}><Search className="h-4 w-4" />
        {t(loading ? 'researchData.loading' : strategy ? 'researchData.runBacktest' : 'researchData.load')}
      </Button>
    </form>}
    {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
    {result && <section className="space-y-4 border-t border-border/60 pt-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{t('researchData.result')}</h3>
        <Badge variant="outline">{result.source_name}</Badge>
      </div>
      {view.chart && <ResearchChart value={result.result} metric={view.chart} compare={view.id === 'compare'} />}
      <ResearchDataset key={generation} value={result.result} actions={row => drilldown(kind, view.id, row, usedFilters, t)} />
      {(cursor || hasNext || numericOffset) && <Button type="button" variant="outline" size="sm" disabled={loading} onClick={() => {
        const next = { ...usedFilters, ...(cursor ? { offset: cursor } : hasNext ? { page: String(page + 1) } : { offset: String(offset + size) }) }
        setValues(next)
        void read(next)
      }}>{t('researchData.nextProviderPage')}<ArrowRight className="h-4 w-4" /></Button>}
    </section>}
  </article>
}

function Workspace({ kind }: { kind: ResearchWorkspace }) {
  const { t: translate } = useTranslation('configuration')
  const t = translate as Translate
  const [params] = useSearchParams()
  const [manifest, setManifest] = useState<ResearchManifest | null>(null)
  const [failed, setFailed] = useState(false)
  const [revision, setRevision] = useState(0)
  const [context, setContext] = useState<Filters>({})
  useEffect(() => {
    const controller = new AbortController()
    loadResearchWorkspace(kind, controller.signal).then(data => { if (!controller.signal.aborted) setManifest(data) })
      .catch(() => { if (!controller.signal.aborted) setFailed(true) })
    return () => controller.abort()
  }, [kind, revision])
  const view = manifest?.views.find(v => v.id === params.get('view')) ?? manifest?.views[0]
  const sections = [...new Set(manifest?.views.map(item => item.section))]
  const retained = Object.fromEntries(inherited.flatMap(key => {
    const value = params.get(key) || context[key]
    return value ? [[key, value]] : []
  }))
  if (failed) return <div className="card space-y-2 p-4" role="alert">
    <p className="text-sm text-destructive">{t('researchData.loadError')}</p>
    <Button variant="outline" size="sm" onClick={() => { setFailed(false); setRevision(v => v + 1) }}>{t('researchData.retry')}</Button>
  </div>
  if (!manifest || !view) return <p role="status" className="text-sm text-muted-foreground">{t('researchData.loading')}</p>
  return <div className="grid items-start gap-4 lg:grid-cols-[minmax(13rem,16rem)_minmax(0,1fr)]">
    <aside className="card min-w-0 space-y-3 p-3">
      <nav aria-label={t('researchData.viewsLabel')} className="scrollbar max-h-52 overflow-y-auto lg:max-h-[65vh]">
        {sections.map(section => <div className="space-y-0.5 py-1.5" key={section}>
          <h3 className="px-2 py-1 text-xs font-medium text-muted-foreground">{t(`researchData.sections.${section}`)}</h3>
          {manifest.views.filter(item => item.section === section).map(item =>
            <Link key={item.id} to={selection(kind, item.id, retained)} aria-current={item.id === view.id ? 'page' : undefined}
              className={`block rounded-lg px-2.5 py-2 text-sm hover:bg-accent ${item.id === view.id ? 'bg-accent font-medium' : 'text-muted-foreground'}`}>
              {t(`researchData.views.${kind}.${item.id}`, { defaultValue: item.title })}
            </Link>)}
        </div>)}
      </nav>
      <div className="space-y-2 border-t border-border/60 px-2 pt-3">
        <Link to="/datasources" className="text-xs text-primary hover:underline">{t('researchData.configure')}</Link>
        <p className="text-xs text-muted-foreground">{t(manifest.sources.length <= 1 ? 'researchData.singleSource' : 'researchData.sourceOrder')}</p>
      </div>
    </aside>
    <ViewPanel key={view.id + '?' + params.toString()} kind={kind} view={view} manifest={manifest}
      params={params} context={context} remember={(key, value) => setContext(old => ({ ...old, [key]: value }))} />
  </div>
}

export default function ResearchDataPage() {
  const { kind } = useParams()
  const { t } = useTranslation('configuration')
  const active = researchWorkspaces.find(item => item === kind)
  return <div className="space-y-5">
    <header className="space-y-1">
      <h1 className="flex items-center gap-2 text-xl font-bold"><Database className="h-5 w-5 text-primary" />{t('researchData.title')}</h1>
      <p className="text-sm text-muted-foreground">{t('researchData.subtitle')}</p>
    </header>
    <nav aria-label={t('researchData.title')} className="scrollbar flex gap-2 overflow-x-auto pb-1">
      {researchWorkspaces.map(key => <NavLink to={`/market-data/${key}`} key={key}
        className={({ isActive }) => `whitespace-nowrap rounded-lg border px-3 py-2 text-sm hover:bg-accent ${isActive ? 'border-primary/30 bg-primary/10 text-primary' : 'border-border/70 text-muted-foreground'}`}>
        {t(`dataSources.types.${key}`)}
      </NavLink>)}
    </nav>
    {active ? <Workspace key={active} kind={active} /> : <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {researchWorkspaces.map(key => <Link to={`/market-data/${key}`} key={key} className="card block min-w-0 space-y-2 p-4 hover:border-primary/30">
        <h2 className="flex items-center justify-between gap-2 font-semibold">{t(`dataSources.types.${key}`)}<ArrowRight className="h-4 w-4 shrink-0 text-primary" /></h2>
        <p className="text-xs leading-relaxed text-muted-foreground">{t(`researchData.summaries.${key}`)}</p>
      </Link>)}
    </div>}
  </div>
}
