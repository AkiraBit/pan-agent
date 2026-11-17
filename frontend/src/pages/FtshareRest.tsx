import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowLeft, ExternalLink, Send } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { getFtshareCatalog, queryFtshare, type FtshareCatalog, type FtshareResult } from '@panwatch/api'
import { Badge } from '@panwatch/base-ui/components/ui/badge'
import { Button } from '@panwatch/base-ui/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@panwatch/base-ui/components/ui/select'
import { FtshareParameters, FtshareTierBadge, ftshareQueryValues, initialFtshareSettings } from '@/components/FtshareParameters'
import { FtshareResponse } from '@/components/FtshareResponse'
import { ALL_FTSHARE_CATEGORIES, FtshareCategoryFilters, matchesFtshareCategory } from '@/components/FtshareCategoryFilters'
import { EndpointSearchInput } from '@/components/DataSourceSearch'
import { endpointSearchTokens, ftshareSearchFields, matchesEndpointSearch, normalizeEndpointTerm } from '@/lib/data-source-search'

type RegisteredOperation = FtshareCatalog['operations'][number]
const ALL = '__all__'

function QueryForm({ operation, configured, paused }: { operation: RegisteredOperation; configured: boolean; paused: boolean }) {
  const { t } = useTranslation('configuration')
  const [settings, setSettings] = useState(() => initialFtshareSettings(operation, operation.settings))
  const [result, setResult] = useState<FtshareResult | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const request = useRef<AbortController | null>(null)
  useEffect(() => () => request.current?.abort(), [])
  const variant = operation.variants[settings.variant]
  const incomplete = variant.parameters.some(param => param.required && !settings.params[param.name]?.trim())

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!configured || paused || !operation.enabled || incomplete || busy) return
    const controller = new AbortController()
    request.current = controller
    setError('')
    setResult(null)
    setBusy(true)
    try {
      const response = await queryFtshare(operation.id, ftshareQueryValues(settings), controller.signal)
      if (!controller.signal.aborted) setResult(response)
    } catch (err) {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : t('fuyao.rest.failed'))
    } finally {
      if (!controller.signal.aborted) setBusy(false)
    }
  }
  return <section className="card min-w-0 space-y-4 p-4 sm:p-6">
    <div className="flex flex-wrap items-center gap-2">
      <h2 className="text-lg font-semibold">{operation.summary}</h2>
      <FtshareTierBadge tier={operation.tier} />
      <a className="ml-auto inline-flex items-center gap-1 text-xs text-primary hover:underline" href={operation.docs_url} target="_blank" rel="noopener noreferrer">
        {t('fuyao.rest.officialDocs')}<ExternalLink className="size-3" />
      </a>
    </div>
    <div className="flex items-center gap-2"><Badge variant="outline">{operation.method}</Badge>
      <code className="min-w-0 break-all text-xs">{variant.path}</code>
    </div>
    <form onSubmit={submit} className="space-y-4 border-t border-border/60 pt-4">
      <FtshareParameters operation={operation} value={settings} onChange={setSettings} disabled={busy} />
      <Button type="submit" size="sm" disabled={!configured || paused || !operation.enabled || incomplete || busy}><Send className="size-4" />
        {t(busy ? 'fuyao.rest.running' : 'fuyao.rest.run')}
      </Button>
      {(!operation.enabled || paused) && <p className="text-xs text-muted-foreground">{t('ftshare.disabled')}</p>}
    </form>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {result && <FtshareResponse result={result} name={operation.id} />}
  </section>
}

export default function FtshareRestPage() {
  const { t } = useTranslation(['configuration', 'common'])
  const [params, setParams] = useSearchParams()
  const [catalog, setCatalog] = useState<FtshareCatalog | null>(null)
  const [revision, retry] = useState(0)
  const [error, setError] = useState(false)
  const [search, setSearch] = useState('')
  const [tier, setTier] = useState(ALL)
  const [category, setCategory] = useState(ALL_FTSHARE_CATEGORIES)
  useEffect(() => {
    const controller = new AbortController()
    getFtshareCatalog(controller.signal).then(value => { if (!controller.signal.aborted) setCatalog(value) })
      .catch(() => { if (!controller.signal.aborted) setError(true) })
    return () => controller.abort()
  }, [revision])
  const operations = catalog?.operations ?? []
  const tokens = endpointSearchTokens(search)
  const filtered = operations.filter(op => (tier === ALL || op.tier === tier) && matchesFtshareCategory(op, category)
    && (!tokens.length || matchesEndpointSearch(ftshareSearchFields(op).map(normalizeEndpointTerm), tokens)))
  const current = filtered.find(op => op.id === params.get('operation')) ?? filtered[0]
  return <div className="space-y-4">
    <Link to="/datasources" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
      <ArrowLeft className="size-4" />{t('dataSources.title')}
    </Link>
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div><h1 className="text-xl font-bold">{t('ftshare.title')}</h1>
        {catalog && <p className="mt-1 text-sm text-muted-foreground">{t('ftshare.counts', {
          free: operations.filter(item => item.tier === 'free').length,
          basic: operations.filter(item => item.tier === 'basic').length,
        })}</p>}
      </div>
      <div className="flex flex-wrap gap-2">
        {catalog && <Button asChild variant="ghost" size="sm"><a href={catalog.source} target="_blank" rel="noopener noreferrer">
          {t('fuyao.rest.officialDocs')}<ExternalLink className="size-3" />
        </a></Button>}
        <Button asChild variant="outline" size="sm"><a href="/settings#sec-data-providers">{t('dataSources.manageKey')}</a></Button>
      </div>
    </header>
    {catalog && !catalog.configured && <p role="status" className="card p-4 text-sm">{t('ftshare.keyNeeded')}</p>}
    {error && <div role="alert" className="card flex items-center gap-3 p-4 text-sm">
      {t('ftshare.loadFailed')}<Button size="sm" variant="outline" onClick={() => { setError(false); retry(n => n + 1) }}>{t('fuyao.retry')}</Button>
    </div>}
    {!catalog && !error && <p role="status">{t('common:states.loading')}</p>}
    {catalog && <div className="card px-3 py-2">
      <FtshareCategoryFilters operations={operations} value={category} onChange={setCategory} />
    </div>}
    {catalog && <div className="grid items-start gap-4 lg:grid-cols-[minmax(17rem,21rem)_minmax(0,1fr)]">
      <aside className="card min-w-0 space-y-3 p-3" aria-label={t('fuyao.rest.open')}>
        <EndpointSearchInput label={t('fuyao.rest.search')} value={search} onChange={setSearch} />
        <Select value={tier} onValueChange={setTier}>
          <SelectTrigger aria-label={t('ftshare.tierFilter')}><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value={ALL}>{t('ftshare.allTiers')}</SelectItem>
            {(['free', 'basic'] as const).map(plan => <SelectItem key={plan} value={plan}>{t(`ftshare.tiers.${plan}`)}</SelectItem>)}</SelectContent>
        </Select>
        <ul key={`${category.group}:${category.subgroup}:${tier}:${search}`} className="scrollbar max-h-64 space-y-1 overflow-y-auto overscroll-contain lg:max-h-[62vh]">
          {filtered.map(op => <li key={op.id}>
            <Button variant={current?.id === op.id ? 'secondary' : 'ghost'} aria-pressed={current?.id === op.id}
              type="button" className="h-auto w-full min-w-0 items-start justify-start gap-2 whitespace-normal px-2 py-2 text-left"
              onClick={() => setParams({ operation: op.id }, { replace: true })}>
              <span className="min-w-0 flex-1"><span className="block text-xs font-medium">{op.summary}</span>
                <code className="break-all text-[10px] font-normal text-muted-foreground">{op.variants[0].path}</code>
              </span><FtshareTierBadge tier={op.tier} />
            </Button>
          </li>)}
        </ul>
        {!filtered.length && <p className="text-xs text-muted-foreground">{t('fuyao.rest.empty')}</p>}
      </aside>
      {current && <QueryForm key={current.id} operation={current} configured={catalog.configured} paused={catalog.paused} />}
    </div>}
  </div>
}
