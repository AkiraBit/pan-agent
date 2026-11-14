import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ChevronRight, ExternalLink, Loader2, Plug, RefreshCw, Unplug } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { fetchAPI } from '@panwatch/api/client'
import { Button } from '@panwatch/base-ui/components/ui/button'
import { Switch } from '@panwatch/base-ui/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@panwatch/base-ui/components/ui/select'
import { useConfirm } from '@panwatch/base-ui/components/ui/confirm-dialog'
import { useToast } from '@panwatch/base-ui/components/ui/toast'
import { formatDate } from '@/i18n/format'

interface Connection {
  id: string; region: 'cn' | 'global'; endpoint: string; authorized: boolean; enabled: boolean
  pending: boolean; checked_at: number | null; error_code: string; docs_url: string
  account_label: string; connected_at: number | null; server_version: string
  tools: Array<{ name: string; title: [string, string]; description: string }>
}
const BASE = '/mcp-connections/longbridge'
const STORAGE = 'panwatch-longbridge-oauth'
type MCPLabel = keyof (typeof import('@/i18n/locales/zh-CN/configuration').configuration)['mcp']

function LongbridgeIcon({ className = '' }: { className?: string }) {
  return <span className={`shrink-0 ${className}`}>
    <img src="https://assets.lbkrs.com/uploads/2e476c46-8bb9-4689-a800-54877351520e/app-icon.svg" alt="Longbridge" referrerPolicy="no-referrer" className="w-full h-full dark:hidden" />
    <img src="https://assets.lbkrs.com/uploads/716a4e35-c078-4fd5-9818-b859ad83b51b/app-icon-dark.svg" alt="Longbridge" referrerPolicy="no-referrer" className="w-full h-full hidden dark:block" />
  </span>
}

function ToolDescription({ text, expandLabel, collapseLabel }: { text: string; expandLabel: string; collapseLabel: string }) {
  const descriptionId = useId()
  const paragraph = useRef<HTMLParagraphElement>(null)
  const [expanded, setExpanded] = useState(false)
  const [overflows, setOverflows] = useState(false)
  useLayoutEffect(() => {
    const element = paragraph.current
    if (!element) return
    const measure = () => {
      const overflowing = element.scrollHeight > parseFloat(getComputedStyle(element).lineHeight) + 1
      setOverflows(overflowing)
      if (!overflowing) setExpanded(false)
    }
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [text])
  return <div className="flex items-start gap-3">
    <p id={descriptionId} ref={paragraph} className={`min-w-0 flex-1 text-xs leading-6 text-muted-foreground whitespace-pre-line break-words ${expanded ? '' : 'line-clamp-1'}`}>{text}</p>
    {overflows && <Button variant="ghost" size="sm" className="h-6 px-2 shrink-0 text-xs" aria-controls={descriptionId} aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>{expanded ? collapseLabel : expandLabel}</Button>}
  </div>
}

export default function MCPPage() {
  const { t, i18n } = useTranslation(['configuration', 'common'])
  const { toast } = useToast()
  const showConfirm = useConfirm()
  const location = useLocation()
  const navigate = useNavigate()
  const [item, setItem] = useState<Connection | null>(null)
  const [region, setRegion] = useState<'cn' | 'global'>('cn')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const callbackStarted = useRef(false)
  const callback = location.pathname.endsWith('/callback')
  const label = (key: MCPLabel) => t(`configuration:mcp.${key}`)
  const load = async () => {
    const result = await fetchAPI<{ items: Connection[] }>('/mcp-connections')
    setItem(result.items[0]); setRegion(result.items[0].region)
  }
  const act = async (operation: () => Promise<void>) => {
    setBusy(true); setError('')
    try { await operation() } catch (e) { setError(e instanceof Error ? e.message : label('failed')) }
    finally { setBusy(false) }
  }
  useEffect(() => {
    if (!callback) { callbackStarted.current = false; void act(load); return }
    if (callbackStarted.current) return
    callbackStarted.current = true
    const query = new URLSearchParams(location.search)
    // Remove the short-lived code from browser history before any other work.
    window.history.replaceState(window.history.state, '', '/integrations/mcp/callback')
    void act(async () => {
      const saved = JSON.parse(sessionStorage.getItem(STORAGE) || 'null')
      sessionStorage.removeItem(STORAGE)
      if (!saved || saved.state !== query.get('state')) throw new Error(label('invalidCallback'))
      await fetchAPI(BASE + '/callback', { method: 'POST', body: JSON.stringify({
        state: saved.state, browser_key: saved.browserKey, code: query.get('code'), error: query.get('error'),
      }) })
      toast(label(query.has('error') ? 'cancelled' : 'authorized'), query.has('error') ? 'info' : 'success')
      navigate('/integrations/mcp', { replace: true })
    })
  }, [callback])
  const authorize = () => act(async () => {
    const browserKey = Array.from(crypto.getRandomValues(new Uint8Array(32)), b => b.toString(16).padStart(2, '0')).join('')
    const result = await fetchAPI<{ authorization_url: string; state: string }>(BASE + '/authorize', {
      method: 'POST', body: JSON.stringify({ region, browser_key: browserKey }), timeoutMs: 45000,
    })
    sessionStorage.setItem(STORAGE, JSON.stringify({ browserKey, state: result.state }))
    window.location.assign(result.authorization_url)
  })
  const change = (path: string, method: string, body?: object) => act(async () => {
    setItem(await fetchAPI<Connection>(BASE + path, { method, body: body ? JSON.stringify(body) : undefined, timeoutMs: 45000 }))
    toast(label(path === '/test' ? 'tested' : 'saved'), 'success')
  })
  const disconnect = async () => {
    if (await showConfirm(label('disconnectConfirm'), { destructive: true })) {
      sessionStorage.removeItem(STORAGE)
      await change('', 'DELETE')
    }
  }
  const connectionStatus = item ? label(item.error_code === 'mcp_authorization_required' ? 'reauthorize' : item.authorized ? item.enabled ? 'enabled' : 'disabled' : item.pending ? 'pending' : 'notAuthorized') : ''
  return <div className="max-w-7xl mx-auto space-y-6">
    <div><h1 className="text-xl font-semibold flex items-center gap-2"><Plug className="w-5 h-5 text-primary" />{label('title')}</h1>
      <p className="text-sm text-muted-foreground mt-2">{label('subtitle')}</p></div>
    {error && <div role="alert" className="rounded-xl border border-destructive/30 p-4 text-sm text-destructive space-y-3">
      <p>{error}</p><Button variant="secondary" size="sm" onClick={() => callback ? navigate('/integrations/mcp', { replace: true }) : void act(load)}>{label('retry')}</Button>
    </div>}
    {callback ? <div className="card p-6" aria-live="polite">{busy ? label('completing') : label('returnHint')}</div> : item ? <div className="grid md:grid-cols-[240px_minmax(0,1fr)] gap-6 items-start">
      <nav aria-label={label('services')} className="card p-3 space-y-3 md:sticky md:top-24">
        <h2 className="px-2 pt-1 text-xs font-medium text-muted-foreground">{label('services')}</h2>
        <a href="#longbridge-details" aria-current="page" className="flex items-center gap-3 rounded-xl border border-primary/15 bg-primary/5 p-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <LongbridgeIcon className="w-10 h-10" />
          <span className="min-w-0 flex-1"><span className="block font-medium">{label('longbridge')}</span><span className="block text-xs text-muted-foreground mt-1">{connectionStatus}</span></span>
          <ChevronRight className="w-4 h-4 text-primary shrink-0" />
        </a>
        <p className="px-2 pb-1 text-xs text-muted-foreground leading-relaxed">{label('builtinHint')}</p>
      </nav>
      <section id="longbridge-details" aria-labelledby="mcp-detail-title" className="card min-w-0 p-5 md:p-7 space-y-6 scroll-mt-24">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-3"><LongbridgeIcon className="w-12 h-12" />
          <div><h2 id="mcp-detail-title" className="font-semibold">{label('longbridge')}</h2><p className="text-xs text-muted-foreground mt-1">{label('builtin')}</p></div></div>
        <span className="text-xs rounded-full px-3 py-1 bg-accent text-foreground">{connectionStatus}</span>
      </div>
      <p className="text-sm text-muted-foreground">{label('description')}</p>
      <dl className="grid sm:grid-cols-3 gap-5 rounded-xl bg-accent/40 p-4">
        <div className="min-w-0"><dt className="text-xs text-muted-foreground">{label('account')}</dt>
          <dd className="text-sm font-medium mt-2 break-words">{item.authorized ? item.account_label || label('accountUnavailable') : label('notAuthorized')}</dd>
          <p className="text-xs text-muted-foreground mt-1 leading-relaxed">{label(item.authorized && item.account_label && !item.account_label.includes('@') ? 'accountFallbackHint' : 'accountHint')}</p></div>
        <div className="min-w-0"><dt className="text-xs text-muted-foreground">{label('connectedAt')}</dt>
          <dd className="text-sm font-medium mt-2">{item.connected_at ? formatDate(item.connected_at * 1000, { dateStyle: 'medium', timeStyle: 'short' }) : item.authorized ? label('timeNotRecorded') : '—'}</dd></div>
        <div className="min-w-0"><dt className="text-xs text-muted-foreground">{label('serverVersion')}</dt>
          <dd className="text-sm font-medium mt-2 break-words">{item.server_version || label(item.checked_at ? 'versionUnavailable' : 'versionPending')}</dd>
          <p className="text-xs text-muted-foreground mt-1 leading-relaxed">{label('versionHint')}</p></div>
      </dl>
      <div className="grid sm:grid-cols-2 gap-5">
        <div className="space-y-2"><label className="text-sm" id="mcp-region-label">{label('region')}</label>
          <Select value={region} onValueChange={value => setRegion(value as 'cn' | 'global')} disabled={busy || item.authorized}>
            <SelectTrigger aria-labelledby="mcp-region-label"><SelectValue /></SelectTrigger><SelectContent>
              <SelectItem value="cn">{label('cn')}</SelectItem><SelectItem value="global">{label('global')}</SelectItem>
            </SelectContent></Select><p className="text-xs text-muted-foreground break-all">{item.authorized ? item.endpoint : region === 'cn' ? 'https://mcp.longbridge.cn' : 'https://mcp.longbridge.com'}</p>
        </div>
        <div className="flex items-center justify-between gap-4"><div><label htmlFor="mcp-enabled" className="text-sm">{label('useAssistant')}</label><p className="text-xs text-muted-foreground mt-1">{label('enableHint')}</p></div>
          <Switch id="mcp-enabled" checked={item.enabled} disabled={busy || !item.authorized || !item.tools.length || !item.checked_at} onCheckedChange={enabled => void change('', 'PUT', { enabled })} />
        </div>
      </div>
      {item.error_code && <p role="status" className="text-sm text-destructive">{label('connectionError')}</p>}
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => void authorize()} disabled={busy}>{busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <ExternalLink className="w-4 h-4" />}{label(item.authorized ? 'authorizeAgain' : 'authorize')}</Button>
        {item.authorized && <><Button variant="secondary" onClick={() => void change('/test', 'POST')} disabled={busy}><RefreshCw className="w-4 h-4" />{label('test')}</Button>
          <Button variant="ghost" onClick={() => void disconnect()} disabled={busy}><Unplug className="w-4 h-4" />{label('disconnect')}</Button></>}
        {item.pending && <Button variant="ghost" disabled={busy} onClick={() => { sessionStorage.removeItem(STORAGE); void change('/authorization', 'DELETE') }}>{label('cancelAuthorization')}</Button>}
      </div>
      <div className="border-t border-border/60 pt-5 space-y-4"><div className="flex justify-between gap-3 flex-wrap"><h3 className="text-sm font-medium">{label('tools')} <span className="text-muted-foreground">{item.tools.length}</span></h3>
        {item.checked_at && <p className="text-xs text-muted-foreground">{t('configuration:mcp.checkedAt', { time: formatDate(item.checked_at * 1000, { dateStyle: 'short', timeStyle: 'short' }) })}</p>}</div>
        <p className="text-xs text-muted-foreground">{label('toolsHint')}</p>
        {item.tools.length ? <ul className="space-y-3">{item.tools.map(tool => <li key={tool.name} className="rounded-xl border border-border/60 p-4 space-y-2">
          <div className="flex flex-wrap gap-x-3 gap-y-1 items-baseline"><h4 className="text-sm font-medium">{tool.title[i18n.language.startsWith('en') ? 1 : 0]}</h4><code className="text-xs text-muted-foreground break-all">{tool.name}</code></div>
          <ToolDescription text={tool.description || label('noDescription')} expandLabel={label('expandDescription')} collapseLabel={label('collapseDescription')} />
        </li>)}</ul> : <p className="text-sm text-muted-foreground">{label('emptyTools')}</p>}
      </div>
      <div className="border-t border-border/60 pt-5 space-y-2 text-xs text-muted-foreground"><p>{label('privacy')}</p><p>{label('disconnectHint')}</p>
        <a href={item.docs_url} target="_blank" rel="noopener noreferrer" className="inline-flex gap-1 items-center text-primary">{label('docs')}<ExternalLink className="w-3 h-3" /></a>
      </div>
      </section>
    </div> : !error && <div className="card p-6 text-sm text-muted-foreground">{t('common:states.loading')}</div>}
  </div>
}
