import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, ExternalLink, Download, Search, Send } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { getFuyaoCatalog, queryFuyao, type FuyaoCatalog, type FuyaoQueryResult } from '@panwatch/api'
import { Badge } from '@panwatch/base-ui/components/ui/badge'
import { Button } from '@panwatch/base-ui/components/ui/button'
import { Input } from '@panwatch/base-ui/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@panwatch/base-ui/components/ui/select'

import { FuyaoParameters, fuyaoQueryValues } from '@/components/FuyaoParameters'

const ANY = '__any__'
const PREVIEW_LIMIT = 80_000
const SETTINGS = '/settings#sec-data-providers'

function downloadJson(name: string, raw: string) {
  const url = URL.createObjectURL(new Blob([raw], { type: 'application/json' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `${name}.json`
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function OperationForm({ operation, configured, paused }: { operation: FuyaoCatalog['operations'][number]; configured: boolean; paused: boolean }) {
  const { t } = useTranslation('configuration')
  const [values, setValues] = useState<Record<string, string>>(() => operation.settings?.params ?? {})
  const [result, setResult] = useState<FuyaoQueryResult | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const pending = useRef<AbortController | null>(null)
  useEffect(() => () => pending.current?.abort(), [])

  const missing = operation.parameters.some(param => param.required && !values[param.name]?.trim())
  const blocked = paused || !operation.enabled

  async function run(event: FormEvent) {
    event.preventDefault()
    if (!configured || blocked || missing || busy) return
    const controller = new AbortController()
    pending.current = controller
    setBusy(true)
    setResult(null)
    setError('')
    try {
      const params = fuyaoQueryValues(values)
      const response = await queryFuyao(operation.id, params, controller.signal)
      if (!controller.signal.aborted) setResult(response)
    } catch (err) {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : t('fuyao.rest.failed'))
    } finally {
      if (!controller.signal.aborted) setBusy(false)
    }
  }

  const failed = result && (result.http_status >= 400 || (result.business_code !== null && result.business_code !== 0))
  return <section className="card min-w-0 space-y-5 p-4 sm:p-6" aria-labelledby="fuyao-operation">
    <div className="space-y-3">
      <div className="flex flex-wrap justify-between gap-2">
        <h2 className="text-lg font-semibold" id="fuyao-operation">{operation.summary}</h2>
        <a className="inline-flex items-center gap-1 text-xs text-primary hover:underline" href={operation.docs_url} target="_blank" rel="noopener noreferrer">
          {t('fuyao.rest.officialDocs')}<ExternalLink className="h-3 w-3" />
        </a>
      </div>
      <div className="flex items-start gap-2 text-xs"><Badge variant="outline">{operation.method}</Badge><code className="min-w-0 break-all leading-6">{operation.path}</code></div>
      <p className="text-sm text-muted-foreground">{operation.description}</p>
    </div>
    <form className="space-y-4 border-t border-border/60 pt-4" onSubmit={run}>
      <FuyaoParameters operation={operation} value={values} onChange={setValues} disabled={busy} />
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" size="sm" disabled={busy || !configured || blocked || missing}><Send className="h-4 w-4" />
          {t(busy ? 'fuyao.rest.running' : 'fuyao.rest.run')}
        </Button>
        {blocked && <Link to="/datasources" className="text-sm text-primary hover:underline">
          {t(paused ? 'fuyao.rest.enableProvider' : 'fuyao.rest.enableOperation')}
        </Link>}
      </div>
    </form>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {result && <section aria-label={t('fuyao.rest.response')} className="space-y-3 border-t border-border/60 pt-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{t('fuyao.rest.response')}</h3>
        {result.response_json !== null && <Button size="sm" variant="outline" type="button"
          onClick={() => downloadJson(operation.id, result.response_json!)}><Download className="h-4 w-4" />{t('fuyao.rest.download')}</Button>}
      </div>
      <div role="status" className="flex flex-wrap items-center gap-2">
        <Badge variant={failed ? 'destructive' : 'outline'}>{t('fuyao.rest.httpStatus', { status: result.http_status })}</Badge>
        {result.business_code !== null && <Badge variant={failed ? 'destructive' : 'outline'}>{t('fuyao.rest.businessCode', { code: result.business_code })}</Badge>}
        {result.request_id && <code className="min-w-0 break-all text-xs text-muted-foreground">{result.request_id}</code>}
      </div>
      {result.response_json === null ? <p className="text-sm text-muted-foreground">{t('fuyao.rest.noResponse')}</p> :
        <pre className="scrollbar max-h-96 overflow-auto rounded-lg bg-muted p-3 whitespace-pre-wrap break-all text-xs">{result.response_json.slice(0, PREVIEW_LIMIT)}</pre>}
      {(result.response_json?.length ?? 0) > PREVIEW_LIMIT &&
        <p className="text-xs text-muted-foreground">{t('fuyao.rest.preview', { count: PREVIEW_LIMIT })}</p>}
    </section>}
  </section>
}

export default function FuyaoRestPage() {
  const { t } = useTranslation(['configuration', 'common'])
  const [catalog, setCatalog] = useState<FuyaoCatalog | null>(null)
  const [failed, setFailed] = useState(false)
  const [revision, setRevision] = useState(0)
  const [search, setSearch] = useState('')
  const [group, setGroup] = useState(ANY)
  const [selected, setSelected] = useState('get_a_share_prices_snapshot')
  useEffect(() => {
    const controller = new AbortController()
    getFuyaoCatalog(controller.signal).then(result => {
      if (!controller.signal.aborted) setCatalog(result)
    }).catch(() => { if (!controller.signal.aborted) setFailed(true) })
    return () => controller.abort()
  }, [revision])

  const groups = [...new Set(catalog?.operations.map(item => item.group))]
  const needle = search.trim().toLowerCase()
  const filtered = catalog?.operations.filter(operation =>
    (group === ANY || group === operation.group) &&
    [operation.summary, operation.id, operation.path, ...operation.parameters.map(p => p.name)].some(value => value.toLowerCase().includes(needle)),
  ) || []
  const current = catalog?.operations.find(operation => operation.id === selected) ?? catalog?.operations[0]
  return <div className="space-y-5">
    <Link to="/datasources" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
      <ArrowLeft className="h-4 w-4" />{t('configuration:dataSources.title')}
    </Link>
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div className="space-y-1">
        <h1 className="text-xl font-bold">{t('configuration:fuyao.rest.title')}</h1>
        <p className="text-sm text-muted-foreground">{t('configuration:fuyao.rest.subtitle')}</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {catalog && <><Badge variant="outline">{t('configuration:fuyao.rest.count', { count: catalog.operations.length })}</Badge>
          <Button asChild variant="ghost" size="sm"><a href={catalog.source} target="_blank" rel="noopener noreferrer">
            {t('configuration:fuyao.rest.officialSpec')}<ExternalLink className="h-3 w-3" />
          </a></Button></>}
        <Button asChild variant="outline" size="sm"><a href={SETTINGS}>{t('configuration:fuyao.manageKey')}</a></Button>
      </div>
    </header>
    {catalog && !catalog.configured && <p className="card p-4 text-sm" role="status">{t('configuration:fuyao.rest.keyNeeded')}</p>}
    {failed && <div className="card flex flex-wrap items-center gap-2 p-4" role="alert">
      <p className="text-sm text-destructive">{t('configuration:fuyao.loadFailed')}</p>
      <Button size="sm" variant="outline" onClick={() => { setFailed(false); setRevision(n => n + 1) }}>{t('configuration:fuyao.retry')}</Button>
    </div>}
    {!catalog && !failed && <p role="status" className="text-sm text-muted-foreground">{t('common:states.loading')}</p>}
    {catalog && current && <div className="grid items-start gap-4 lg:grid-cols-[minmax(16rem,20rem)_minmax(0,1fr)]">
      <aside className="card min-w-0 space-y-3 p-3" aria-label={t('configuration:fuyao.rest.open')}>
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-3.5 h-4 w-4 text-muted-foreground" />
          <Input type="search" aria-label={t('configuration:fuyao.rest.search')} placeholder={t('configuration:fuyao.rest.search')}
            value={search} onChange={event => setSearch(event.target.value)} className="pl-9" />
        </div>
        <Select value={group} onValueChange={setGroup}>
          <SelectTrigger aria-label={t('configuration:fuyao.rest.filter')}><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>{t('configuration:fuyao.rest.allGroups')}</SelectItem>
            {groups.map(id => <SelectItem key={id} value={id}>{t(`configuration:fuyao.services.${id}`)}</SelectItem>)}
          </SelectContent>
        </Select>
        <p className="px-1 text-xs text-muted-foreground">{t('configuration:fuyao.rest.count', { count: filtered.length })}</p>
        <ul className="scrollbar max-h-60 space-y-1 overflow-y-auto overscroll-contain lg:max-h-[62vh]">
          {filtered.map(operation => <li key={operation.id}>
            <Button variant={current.id === operation.id ? 'secondary' : 'ghost'} aria-pressed={current.id === operation.id}
              type="button" className="h-auto w-full min-w-0 items-start gap-2 whitespace-normal px-2 py-2 text-left"
              onClick={() => setSelected(operation.id)}>
              <span className="mt-0.5 shrink-0 text-[10px] font-semibold text-primary">{operation.method}</span>
              <span className="min-w-0 flex-1">
                <span className="block text-xs font-medium">{operation.summary}</span>
                <code className="break-all text-[10px] font-normal text-muted-foreground">{operation.path}</code>
              </span>
            </Button>
          </li>)}
        </ul>
        {!filtered.length && <p className="px-1 text-xs text-muted-foreground">{t('configuration:fuyao.rest.empty')}</p>}
      </aside>
      <OperationForm key={current.id} operation={current} configured={catalog.configured} paused={catalog.paused} />
    </div>}
  </div>
}
